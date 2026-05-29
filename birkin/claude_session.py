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

from .proc import cli_argv

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
                 turn_timeout: float = 300.0):
        self.model = model
        self.permission_mode = permission_mode
        self.cli_access = cli_access
        self.append_system_prompt = append_system_prompt
        self.add_dirs = list(add_dirs or [])
        self.extra_args = list(extra_args or [])
        self.cwd = cwd
        self.startup_timeout = float(startup_timeout)
        self.turn_timeout = float(turn_timeout)

        self._proc: Optional[subprocess.Popen] = None
        self._q: "queue.Queue[tuple[str, Optional[str]]]" = queue.Queue()
        self._lock = threading.Lock()
        self._session_id: Optional[str] = None
        self._sys_file: Optional[Path] = None

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

    def _build_argv(self) -> list[str]:
        parts = ["claude", "--print",
                 "--input-format", "stream-json",
                 "--output-format", "stream-json",
                 "--verbose"]
        if self.cli_access == "full":
            parts.append("--dangerously-skip-permissions")
        else:
            parts += ["--permission-mode", self.permission_mode]
        if self.model and self.model not in ("claude-code", "default", ""):
            parts += ["--model", self.model]
        sys_file = self._ensure_sys_file()
        if sys_file is not None:
            parts += ["--append-system-prompt-file", str(sys_file)]
        for d in self.add_dirs:
            parts += ["--add-dir", d]
        parts += self.extra_args
        return cli_argv(parts)

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        """Spawn the process and begin draining stdout/stderr into the queue."""
        self.close()
        argv = self._build_argv()  # also materializes the system-prompt temp file
        # Bounded so a long, --verbose turn can't grow stdout/stderr without limit.
        q: "queue.Queue[tuple[str, Optional[str]]]" = queue.Queue(maxsize=2048)
        try:
            self._proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1, errors="replace",
                cwd=self.cwd)
        except OSError:
            self._cleanup_sys_file()  # don't leak the temp file if spawn fails
            raise
        self._q = q
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

    def close(self) -> None:
        if self._proc is not None:
            try:
                if self._proc.stdin and not self._proc.stdin.closed:
                    self._proc.stdin.close()
            except OSError:
                pass
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
                    self._proc.kill()
                    self._proc.wait(timeout=2)
                except (OSError, AttributeError, ValueError,
                        subprocess.TimeoutExpired):
                    pass
            self._proc = None
        self._session_id = None
        self._cleanup_sys_file()

    def reset(self) -> None:
        """Drop the conversation: kill the process so the next ask() starts fresh."""
        self.close()

    # -- one turn ----------------------------------------------------------

    def _send(self, text: str) -> None:
        # Explicit check (not assert — asserts are stripped under `python -O`).
        if self._proc is None or self._proc.stdin is None:
            raise ClaudeSessionError("no live Claude process to send to")
        msg = {"type": "user", "message": {"role": "user", "content": text}}
        self._proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def ask(self, text: str, on_text: StreamCallback = None,
            timeout: Optional[float] = None) -> str:
        """Send one user turn; return the assistant's final text.

        Serialized: one turn at a time per session. On a dead process the
        session is restarted once (losing prior context) and the turn retried.
        """
        text = (text or "").strip()
        if not text:
            return ""
        with self._lock:
            if not self.is_alive():
                self.start()
            try:
                return self._turn(text, on_text, timeout)
            except ClaudeSessionError:
                # Process died mid-turn — restart fresh and retry once. The new
                # process has NO prior context; surface that it happened.
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
        except (OSError, BrokenPipeError, AssertionError) as exc:
            raise ClaudeSessionError(f"send failed: {exc}") from exc

        final_text = ""
        assistant_text = ""
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
            elif etype == "assistant":
                piece = _assistant_text(event)
                if piece:
                    assistant_text = piece
                    if on_text:
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
