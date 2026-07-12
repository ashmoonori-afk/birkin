"""A persistent, warm Codex session over `codex app-server` (JSON-RPC/stdio).

The codex-cli provider normally runs one `codex exec` per message, paying the
full CLI cold start every reply — measured at ~17 s boot / ~37 s total for a
trivial turn (docs/hermes-comparison.md §6). This module keeps **one
long-lived** `codex app-server` process per conversation, the same fix the
hermes agent ships, speaking the app-server protocol (codex 0.125+):

    newline-delimited JSON-RPC 2.0 over stdio
    initialize + initialized          (handshake)
    thread/start {cwd}                -> thread id (conversation context)
    turn/start {threadId, input}      -> item/* notifications, turn/completed

Streaming granularity is per **item** (codex emits whole agentMessage items,
not token deltas) — each completed agent message is forwarded to ``on_text``
as an append-style piece, so channels can show progress mid-turn.

Headless safety: server-initiated approval requests (exec command,
apply_patch) are **auto-declined** — a chat gateway must never approve
writes on its own. Codex's own default sandbox (read-only unless the user's
~/.codex/config.toml says otherwise) applies.

The system prompt (persona + memory digest) has no app-server-level slot, so
it is sent as a preamble block on the FIRST turn of the thread.

Pure standard library: ``subprocess`` + reader thread + ``queue``.
Interface-compatible with :class:`birkin.claude_session.ClaudeStreamSession`
(``ask/close/reset/is_alive``) so the gateway session pool can hold either.
"""

from __future__ import annotations

import itertools
import json
import os
import queue
import re
import subprocess
import threading
import time
from typing import Any, Callable, Optional

from .proc import cli_argv, kill_tree

StreamCallback = Optional[Callable[[str], None]]

_MODEL_RE = re.compile(r"[A-Za-z0-9._:-]+")


class CodexSessionError(RuntimeError):
    """Raised when the persistent codex process cannot produce a reply."""


class CodexAppServerSession:
    """One warm ``codex app-server`` process driven over JSON-RPC stdio."""

    def __init__(self, *, model: Optional[str] = None,
                 cwd: Optional[str] = None,
                 preamble: str = "",
                 startup_timeout: float = 90.0,
                 turn_timeout: float = 300.0,
                 request_timeout: float = 30.0):
        self.model = model
        self.cwd = cwd
        self.preamble = preamble
        self.startup_timeout = float(startup_timeout)
        self.turn_timeout = float(turn_timeout)
        self.request_timeout = float(request_timeout)

        self._proc: Optional[subprocess.Popen] = None
        self._notes: "queue.Queue[Optional[dict]]" = queue.Queue()
        self._replies: dict[Any, "queue.Queue[dict]"] = {}
        self._replies_lock = threading.Lock()
        self._stdin_lock = threading.Lock()
        self._ids = itertools.count(1)
        self._lock = threading.Lock()          # one turn at a time
        self._thread_id: Optional[str] = None
        self._sent_preamble = False
        self._closed = False

    # -- process lifecycle ---------------------------------------------------

    def _build_argv(self) -> list[str]:
        parts = ["codex", "app-server"]
        if self.model:
            # -c overrides ~/.codex/config.toml; value parsed as TOML. The
            # model name is interpolated into a quoted TOML string, so only a
            # conservative charset is allowed (a `"` would break the parse —
            # reachable via /models, which accepts any string for codex).
            if not _MODEL_RE.fullmatch(self.model):
                raise CodexSessionError(
                    f"unsafe codex model name: {self.model!r}")
            parts += ["-c", f'model="{self.model}"']
        return cli_argv(parts)

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        """Spawn + handshake + thread/start. Idempotent per live process."""
        self._terminate(mark_closed=False)
        try:
            self._proc = subprocess.Popen(
                self._build_argv(), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
                cwd=self.cwd, env=dict(os.environ))
        except OSError as exc:
            raise CodexSessionError(f"failed to spawn codex app-server: {exc}")
        # Fresh queue per process, passed BY VALUE to the reader thread: a
        # slow reader from a killed predecessor keeps writing into ITS queue,
        # never into the new turn's (same pattern as claude_session).
        notes: "queue.Queue[Optional[dict]]" = queue.Queue()
        self._notes = notes
        threading.Thread(target=self._read_stdout,
                         args=(self._proc.stdout, notes), daemon=True).start()
        try:
            self.request("initialize", {
                "clientInfo": {"name": "birkin", "title": "birkin gateway",
                               "version": "1.0"},
                "capabilities": {}}, timeout=self.startup_timeout)
            self._notify("initialized")
            result = self.request("thread/start",
                                  {"cwd": self.cwd or os.getcwd()},
                                  timeout=self.startup_timeout)
            thread_obj = result.get("thread") or {}
            # Field name has moved across codex versions — accept them all.
            self._thread_id = (thread_obj.get("id")
                               or thread_obj.get("sessionId")
                               or result.get("sessionId")
                               or result.get("threadId"))
            if not self._thread_id:
                raise CodexSessionError(
                    f"thread/start returned no thread id "
                    f"(keys: {sorted(result)})")
        except Exception:
            # A half-initialized child must not linger: is_alive() would lie
            # and the next ask() would send turn/start with threadId=None.
            self._terminate(mark_closed=False)
            raise
        self._sent_preamble = False

    def _terminate(self, *, mark_closed: bool) -> None:
        self._closed = mark_closed
        if self._proc is not None:
            try:
                if self._proc.stdin and not self._proc.stdin.closed:
                    self._proc.stdin.close()
            except OSError:
                pass
            if os.name == "nt":
                kill_tree(self._proc)
            else:
                try:
                    self._proc.terminate()
                except OSError:
                    pass
            try:
                self._proc.wait(timeout=3)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                try:
                    kill_tree(self._proc)
                    self._proc.wait(timeout=2)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    pass
            self._proc = None
        self._thread_id = None

    def close(self) -> None:
        """Retire for good (gateway /new + shutdown)."""
        self._terminate(mark_closed=True)

    def reset(self) -> None:
        """Drop the conversation; next ask() starts a fresh process."""
        self._terminate(mark_closed=False)

    # -- JSON-RPC plumbing -----------------------------------------------------

    def _send(self, obj: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise CodexSessionError("no live codex process to send to")
        try:
            with self._stdin_lock:
                self._proc.stdin.write(json.dumps(obj, ensure_ascii=False)
                                       + "\n")
                self._proc.stdin.flush()
        except (OSError, BrokenPipeError, ValueError) as exc:
            # ValueError covers "I/O operation on closed file": close()/
            # reset() from another thread (gateway shutdown/restart) closes
            # stdin before _proc is nulled — surface it as the graceful
            # session error, not a raw ValueError.
            raise CodexSessionError(f"send failed: {exc}") from exc

    def _notify(self, method: str, params: Optional[dict] = None) -> None:
        self._send({"method": method, "params": params or {}})

    def request(self, method: str, params: Optional[dict] = None,
                timeout: Optional[float] = None) -> dict:
        rid = next(self._ids)
        q: "queue.Queue[dict]" = queue.Queue(maxsize=1)
        with self._replies_lock:
            self._replies[rid] = q
        try:
            self._send({"id": rid, "method": method, "params": params or {}})
            try:
                msg = q.get(timeout=timeout or self.request_timeout)
            except queue.Empty:
                raise CodexSessionError(f"{method} timed out")
        finally:
            with self._replies_lock:
                self._replies.pop(rid, None)
        if "error" in msg:
            err = msg["error"] or {}
            raise CodexSessionError(
                f"{method} failed: {err.get('message')} ({err.get('code')})")
        return msg.get("result") or {}

    def _read_stdout(self, pipe: Any, notes: "queue.Queue") -> None:
        try:
            for line in pipe:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if "id" in msg and ("result" in msg or "error" in msg):
                    with self._replies_lock:
                        q = self._replies.get(msg["id"])
                    if q is not None:
                        try:
                            q.put_nowait(msg)
                        except queue.Full:
                            pass
                elif "id" in msg and "method" in msg:
                    # Server-initiated request = an approval ask. A headless
                    # gateway never approves writes: decline immediately.
                    # Never let a decline failure kill the reader thread.
                    try:
                        self._send({"id": msg["id"],
                                    "result": {"decision": "denied"}})
                    except Exception:
                        pass
                elif "method" in msg:
                    notes.put(msg)
        except (ValueError, OSError):
            pass
        finally:
            notes.put(None)                # sentinel: THIS pipe closed

    # -- one turn ----------------------------------------------------------

    def ask(self, text: str, on_text: StreamCallback = None,
            timeout: Optional[float] = None) -> str:
        """Send one user turn; return the final agent text.

        ``on_text`` receives append-style pieces (one per completed agent
        message item — codex streams items, not tokens)."""
        text = (text or "").strip()
        if not text:
            return ""
        with self._lock:
            if self._closed:
                raise CodexSessionError("session was closed")
            if not self.is_alive():
                self.start()
            try:
                return self._turn(text, on_text, timeout)
            except CodexSessionError:
                if self._closed:
                    raise
                print("[birkin] codex session restarted (prior context lost)",
                      flush=True)
                self.start()
                return self._turn(text, on_text, timeout)

    def _turn(self, text: str, on_text: StreamCallback,
              timeout: Optional[float]) -> str:
        while True:                        # drop stale events from a prior turn
            try:
                stale = self._notes.get_nowait()
            except queue.Empty:
                break
            if stale is None:
                raise CodexSessionError("codex process exited unexpectedly")
        carries_preamble = bool(self.preamble) and not self._sent_preamble
        if carries_preamble:
            text = (f"<system-context>\n{self.preamble}\n</system-context>\n\n"
                    + text)
        self.request("turn/start", {
            "threadId": self._thread_id,
            "input": [{"type": "text", "text": text}]})
        if carries_preamble:
            # Only mark delivered once turn/start was ACCEPTED — if it raises
            # (timeout on a live process), the next turn re-attaches the
            # persona/memory block instead of silently dropping it forever.
            self._sent_preamble = True
        deadline = time.monotonic() + (timeout or self.turn_timeout)
        final = ""
        streamed = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodexSessionError(
                    f"codex turn timed out after "
                    f"{timeout or self.turn_timeout:.0f}s")
            try:
                note = self._notes.get(timeout=remaining)
            except queue.Empty:
                raise CodexSessionError("codex turn timed out")
            if note is None:
                raise CodexSessionError("codex process exited unexpectedly")
            method = note.get("method") or ""
            params = note.get("params") or {}
            if method == "item/completed":
                piece = _agent_text(params.get("item") or {})
                if piece:
                    final = piece          # last agent message is canonical
                    if on_text:
                        # append-style contract: emit only what's new
                        on_text(("\n\n" if streamed else "") + piece)
                        streamed += 1
            elif method == "turn/completed":
                turn = params.get("turn") or {}
                status = turn.get("status")
                if status and status not in ("completed", "interrupted"):
                    err = turn.get("error") or {}
                    return (f"[birkin] codex error: "
                            f"{str(err.get('message') or status)[:400]}")
                return final


def _agent_text(item: dict) -> str:
    """Extract assistant text from a completed item (agent messages only)."""
    itype = str(item.get("type") or item.get("itemType") or "")
    if itype.replace("_", "").lower() != "agentmessage":
        return ""
    content = item.get("text") or item.get("content") or ""
    if isinstance(content, list):
        content = "".join(str(c.get("text", "")) if isinstance(c, dict)
                          else str(c) for c in content)
    return str(content).strip()
