"""A persistent, warm Claude Code session over the stream-json protocol.

The ``claude-cli`` provider normally spawns a fresh ``claude -p`` process per
message. That pays the full Claude Code cold-start (config, plugins, MCP servers,
and — until fixed — the global hooks) on *every* reply, which is the dominant
latency. This module keeps **one long-lived** ``claude`` process per
conversation and feeds it messages over stdin using Claude Code's realtime
streaming I/O::

    claude --print --input-format stream-json --output-format stream-json --verbose

Input is newline-delimited JSON user messages::

    {"type": "user", "message": {"role": "user", "content": "..."}}

Output is a stream of JSON events per line: ``system`` (init), ``assistant``
(the reply), ``result`` (final, carries ``.result`` text + timings), plus
``rate_limit_event`` and partials. The process stays alive and **keeps the
conversation context**, so only the new user turn is sent each time — the
cold-start is paid once, warm turns are ~model-time.

Billing stays on the Claude subscription (this *is* Claude Code), so it remains
free — no API key, no third-party ``extra_usage``.

Pure standard library: ``subprocess`` + reader threads + ``queue``.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .proc import claude_child_env, cli_argv, kill_tree

StreamCallback = Optional[Callable[[str], None]]


class ClaudeSessionError(RuntimeError):
    """Raised when the persistent Claude process cannot produce a reply."""


class ClaudeStreamSession:
    """One warm ``claude`` process driven over stream-json stdin/stdout."""

    def __init__(self, *, model: Optional[str] = None,
                 permission_mode: str = "acceptEdits",
                 cli_access: str = "workspace",
                 append_system_prompt: str = "",
                 add_dirs: Optional[list[str]] = None,
                 extra_args: Optional[list[str]] = None,
                 cwd: Optional[str] = None,
                 startup_timeout: float = 90.0,
                 turn_timeout: float = 300.0,
                 settings: Optional[dict] = None,
                 env_extra: Optional[dict] = None):
        self.model = model
        self.permission_mode = permission_mode
        self.cli_access = cli_access
        self.append_system_prompt = append_system_prompt
        self.add_dirs = list(add_dirs or [])
        self.extra_args = list(extra_args or [])
        self.cwd = cwd
        self.startup_timeout = float(startup_timeout)
        self.turn_timeout = float(turn_timeout)
        # Claude Code settings overrides for THIS child only (e.g.
        # {"disableAllHooks": true} for a headless service — the user's
        # interactive hook stack costs seconds per turn; measured in
        # docs/hermes-comparison.md §6). Written to a temp file and passed
        # via --settings, same quoting rationale as the system prompt.
        self.settings = dict(settings or {})
        # Extra child env (e.g. MAX_THINKING_TOKENS=0 for fast chat turns).
        self.env_extra = {k: str(v) for k, v in (env_extra or {}).items()}

        self._proc: Optional[subprocess.Popen] = None
        self._q: "queue.Queue[tuple[str, Optional[str]]]" = queue.Queue()
        self._lock = threading.Lock()
        self._session_id: Optional[str] = None
        self._sys_file: Optional[Path] = None
        self._settings_file: Optional[Path] = None
        # Set by close() (terminal retire, e.g. gateway /new). ask() must NOT
        # resurrect a deliberately-closed session: a racing in-flight turn could
        # otherwise restart a process on an object the gateway already dropped,
        # leaking it and replying to the old turn after the user said "new".
        self._closed = False

    # -- process lifecycle -------------------------------------------------

    def _ensure_sys_file(self) -> Optional[Path]:
        """Materialize the system prompt to a temp file.

        Passing a multi-line system prompt (with arbitrary memory text) as a
        ``cmd /c`` argument on Windows risks quoting/length breakage, so the
        prompt is always handed to Claude via ``--append-system-prompt-file``.
        """
        if not self.append_system_prompt:
            return None
        if self._sys_file and self._sys_file.exists():
            return self._sys_file
        fd, path = tempfile.mkstemp(suffix="-birkin-sys.md")
        # The file holds the persona + a full memory snapshot; restrict it to the
        # owner (no-op on Windows, enforced on POSIX) rather than relying on the
        # OS default ACL.
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(self.append_system_prompt)
        self._sys_file = Path(path)
        return self._sys_file

    def _cleanup_sys_file(self) -> None:
        if self._sys_file is not None:
            try:
                self._sys_file.unlink()
            except OSError:
                pass
            self._sys_file = None
        if self._settings_file is not None:
            try:
                self._settings_file.unlink()
            except OSError:
                pass
            self._settings_file = None

    def _ensure_settings_file(self) -> Optional[Path]:
        """Materialize the per-child settings overrides to a temp file."""
        if not self.settings:
            return None
        if self._settings_file and self._settings_file.exists():
            return self._settings_file
        fd, path = tempfile.mkstemp(suffix="-birkin-settings.json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.settings, fh)
        self._settings_file = Path(path)
        return self._settings_file

    def child_env(self) -> dict[str, str]:
        """Environment for the child process: claude_child_env + env_extra."""
        env = claude_child_env()
        env.update(self.env_extra)
        return env

    def _build_argv(self) -> list[str]:
        parts = ["claude", "--print",
                 "--input-format", "stream-json",
                 "--output-format", "stream-json",
                 "--verbose",
                 # token-level deltas so channels can stream partial replies
                 # (hermes-style perceived latency; see hermes-comparison §6)
                 "--include-partial-messages"]
        if self.cli_access == "full":
            parts.append("--dangerously-skip-permissions")
        else:
            parts += ["--permission-mode", self.permission_mode]
        if self.model and self.model not in ("claude-code", "default", ""):
            parts += ["--model", self.model]
        sys_file = self._ensure_sys_file()
        if sys_file is not None:
            parts += ["--append-system-prompt-file", str(sys_file)]
        settings_file = self._ensure_settings_file()
        if settings_file is not None:
            parts += ["--settings", str(settings_file)]
        for d in self.add_dirs:
            parts += ["--add-dir", d]
        parts += self.extra_args
        return cli_argv(parts)

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        """Spawn the process and begin draining stdout/stderr into the queue."""
        self._terminate(mark_closed=False)  # tear down any prior proc; stay open
        # Bounded so a long, --verbose turn can't grow stdout/stderr without limit.
        q: "queue.Queue[tuple[str, Optional[str]]]" = queue.Queue(maxsize=2048)
        try:
            # _build_argv materializes the sys-prompt/settings temp files, so
            # its own failures (e.g. cli_argv's metacharacter ValueError) must
            # clean them up too — not just a Popen failure.
            argv = self._build_argv()
            self._proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1, encoding="utf-8",
                errors="replace", cwd=self.cwd, env=self.child_env())
        except (OSError, ValueError):
            self._cleanup_sys_file()  # don't leak temp files on any failure
            raise
        self._q = q
        # Register the child so the orphan reaper can reclaim it if THIS birkin
        # process dies ungracefully before close() runs (procreg).
        try:
            from . import procreg
            procreg.register(self._proc.pid)
        except Exception:
            pass
        # The queue is passed BY VALUE to each drain thread: on a later restart()
        # self._q is replaced, and the old threads must keep writing to *their*
        # (now-abandoned) queue, never into the fresh one.
        threading.Thread(target=self._drain, args=(self._proc.stdout, "out", q),
                         daemon=True).start()
        threading.Thread(target=self._drain, args=(self._proc.stderr, "err", q),
                         daemon=True).start()

    @staticmethod
    def _drain(pipe: Any, tag: str, q: "queue.Queue") -> None:
        def _offer(item: tuple[str, Optional[str]]) -> None:
            # Never block forever. The queue only fills BETWEEN turns (nothing is
            # consuming); during a turn the consumer drains it faster than Claude
            # emits. So on Full we drop the OLDEST (stale) event to make room,
            # which keeps the newest protocol events and the sentinel — instead
            # of the old blocking put() that could deadlock the reader thread.
            while True:
                try:
                    q.put_nowait(item)
                    return
                except queue.Full:
                    try:
                        q.get_nowait()  # drop the oldest stale event for room
                    except queue.Empty:
                        pass  # consumer raced us empty; loop and the put fits
        try:
            for line in pipe:
                item = (tag, line.rstrip("\n"))
                if tag == "err":
                    try:
                        q.put_nowait(item)  # diagnostics: drop if backed up
                    except queue.Full:
                        pass
                else:
                    _offer(item)  # protocol events: keep newest, never deadlock
        except (ValueError, OSError):
            pass
        finally:
            _offer((tag, None))  # sentinel: this pipe closed

    def _terminate(self, *, mark_closed: bool) -> None:
        self._closed = mark_closed
        if self._proc is not None:
            try:
                if self._proc.stdin and not self._proc.stdin.closed:
                    self._proc.stdin.close()
            except OSError:
                pass
            # POSIX: SIGTERM lets claude flush gracefully. Windows: terminate()
            # only hits the cmd.exe shim (see proc.cli_argv) and leaves the
            # claude→node tree as an orphan, so kill the whole tree there.
            if os.name == "nt":
                kill_tree(self._proc)
            else:
                try:
                    self._proc.terminate()
                except OSError:
                    pass
            # Reap the child so it doesn't linger as a zombie (POSIX) across the
            # many close()/restart cycles a long-running gateway accumulates.
            try:
                self._proc.wait(timeout=3)
            except (subprocess.TimeoutExpired, OSError, AttributeError, ValueError):
                try:
                    kill_tree(self._proc)
                    self._proc.wait(timeout=2)
                except (OSError, AttributeError, ValueError,
                        subprocess.TimeoutExpired):
                    pass
            try:  # graceful terminate -> drop it from the orphan registry
                from . import procreg
                procreg.unregister(self._proc.pid)
            except Exception:
                pass
            self._proc = None
        self._session_id = None
        self._cleanup_sys_file()

    def close(self) -> None:
        """Retire this session for good (gateway /new + shutdown). A subsequent
        ask() will refuse rather than silently spawn a new process."""
        self._terminate(mark_closed=True)

    def reset(self) -> None:
        """Drop the conversation but keep the object reusable: the next ask()
        starts a fresh process."""
        self._terminate(mark_closed=False)

    # -- one turn ----------------------------------------------------------

    def _send(self, text: str) -> None:
        # Explicit check (not assert — asserts are stripped under `python -O`).
        if self._proc is None or self._proc.stdin is None:
            raise ClaudeSessionError("no live Claude process to send to")
        msg = {"type": "user", "message": {"role": "user", "content": text}}
        self._proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def steer(self, text: str) -> bool:
        """Deliver a mid-turn instruction WITHOUT cancelling the turn.

        Written straight to the child's stdin like interrupt() does, as a
        normal user message; Claude Code applies it to the running turn. The
        blocked _turn keeps waiting for its single result event, and the
        stale-event flush at the start of the next turn absorbs the case where
        an older CLI queues it as a separate turn instead. Best-effort — never
        raises."""
        text = (text or "").strip()
        if not text or self._proc is None or self._proc.stdin is None:
            return False
        try:                    # no turn lock: this only writes to stdin
            self._send(text)
            return True
        except (OSError, ValueError, ClaudeSessionError):
            return False

    def interrupt(self) -> bool:
        """Cancel the in-flight turn (called from another thread). Sends the
        stream-json control interrupt; if the CLI version ignores it the turn
        simply finishes normally (the caller waits bounded). Best-effort —
        never raises."""
        if self._proc is None or self._proc.stdin is None:
            return False
        try:                    # no turn lock: this only writes to stdin
            self._proc.stdin.write(json.dumps(
                {"type": "control_request",
                 "request": {"subtype": "interrupt"}}) + "\n")
            self._proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def ask(self, text: str, on_text: StreamCallback = None,
            timeout: Optional[float] = None) -> str:
        """Send one user turn; return the assistant's final text.

        ``on_text`` receives APPEND-style pieces (token deltas when the CLI
        emits partial messages; whole assistant messages as a fallback) —
        concatenating every piece approximates the final text.

        Serialized: one turn at a time per session. On a dead process the
        session is restarted once (losing prior context) and the turn retried.
        """
        text = (text or "").strip()
        if not text:
            return ""
        with self._lock:
            if self._closed:
                raise ClaudeSessionError("session was closed")
            if not self.is_alive():
                self.start()
            try:
                return self._turn(text, on_text, timeout)
            except ClaudeSessionError:
                # Process died mid-turn. If it was closed out from under us
                # (e.g. gateway /new dropped this session), do NOT resurrect it —
                # that would leak a process and answer a retired conversation.
                if self._closed:
                    raise
                # Otherwise it died on its own — restart fresh and retry once.
                # The new process has NO prior context; surface that it happened.
                print("[birkin] claude session restarted (prior context lost)",
                      flush=True)
                self.start()
                return self._turn(text, on_text, timeout)

    def _turn(self, text: str, on_text: StreamCallback,
              timeout: Optional[float]) -> str:
        # Discard any stale events from a PRIOR turn before sending this one, so
        # we never mistake an old event for this turn's reply. A death sentinel
        # is honoured (not silently dropped) so a dead process still restarts.
        while True:
            try:
                _tag, _line = self._q.get_nowait()
            except queue.Empty:
                break
            if _line is None and _tag == "out":
                raise ClaudeSessionError("Claude process exited unexpectedly.")
        deadline = time.monotonic() + (timeout or self.turn_timeout)
        try:
            self._send(text)
        except (OSError, BrokenPipeError, AssertionError, ValueError) as exc:
            # ValueError covers "I/O operation on closed file": a concurrent
            # close()/reset() (gateway shutdown/restart) closes stdin before
            # _proc is nulled — route it through the graceful session path.
            raise ClaudeSessionError(f"send failed: {exc}") from exc

        final_text = ""
        assistant_text = ""
        saw_delta = False   # partial deltas seen -> assistant events stay silent
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ClaudeSessionError(
                    f"[birkin] Claude stream timed out after "
                    f"{timeout or self.turn_timeout:.0f}s.")
            try:
                tag, line = self._q.get(timeout=remaining)
            except queue.Empty:
                raise ClaudeSessionError("[birkin] Claude stream timed out.")
            if line is None:
                if tag == "out":  # stdout closed -> process gone
                    raise ClaudeSessionError("Claude process exited unexpectedly.")
                continue  # stderr closed: ignore
            if tag == "err":
                continue  # diagnostics only
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = event.get("type")
            if etype == "system" and event.get("session_id"):
                self._session_id = event.get("session_id")
            elif etype == "stream_event":
                # --include-partial-messages: token-level text deltas. These
                # are what on_text consumers stream to the user; the later
                # `assistant` event is kept only as the authoritative full
                # text (and as the on_text fallback when no deltas arrived).
                ev = event.get("event") or {}
                if ev.get("type") == "content_block_delta":
                    d = ev.get("delta") or {}
                    if d.get("type") == "text_delta" and d.get("text"):
                        saw_delta = True
                        if on_text:
                            on_text(d["text"])
            elif etype == "assistant":
                piece = _assistant_text(event)
                if piece:
                    assistant_text = piece
                    if on_text and not saw_delta:
                        on_text(piece)
            elif etype == "result":
                final_text = (event.get("result")
                              or assistant_text
                              or "").strip()
                if event.get("is_error"):
                    err = event.get("result") or event.get("subtype") or "error"
                    return f"[birkin] Claude error: {str(err)[:400]}"
                return final_text
        # unreachable


def _assistant_text(event: dict[str, Any]) -> str:
    """Extract concatenated text blocks from an ``assistant`` stream event."""
    msg = event.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content
                       if isinstance(b, dict) and b.get("type") == "text")
    return ""
