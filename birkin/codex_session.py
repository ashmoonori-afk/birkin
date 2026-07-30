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

One exception, opt-in per session via ``birkin_mcp``: a tool call to birkin's
OWN MCP server is approved. Codex asks for those with an MCP elicitation
(``mcpServer/elicitation/request``, ``serverName: "birkin"``), and declining
them left the gateway unable to write memory at all — asked to remember a
name, it answered that it had no memory path. The tools behind that server
are birkin's own gated surface: memory (reversible files under the birkin
home), skills (guard-scanned), and ``propose_action``, which queues to
``birkin review`` instead of executing. Any other MCP server still declines.

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

# Codex asks permission for an MCP tool call with an MCP *elicitation*, not
# with its exec/apply_patch approval shape. Captured live from codex 0.145:
#   {"method": "mcpServer/elicitation/request", "id": 0, "params": {
#      "serverName": "birkin", "mode": "form", "requestedSchema": {...},
#      "message": "Allow the birkin MCP server to run tool \"memory_search\"?",
#      "_meta": {"codex_approval_kind": "mcp_tool_call", ...}}}
# The reply is the MCP elicitation result ({"action": ...}), not codex's
# {"decision": ...} — answering with the latter reads as a rejection.
_MCP_ELICITATION = "mcpServer/elicitation/request"


def _server_name() -> str:
    from .mcp_server import _SERVER_NAME
    return _SERVER_NAME


class CodexSessionError(RuntimeError):
    """Raised when the persistent codex process cannot produce a reply."""


class CodexTurnTimeout(CodexSessionError):
    pass


class CodexAppServerSession:
    """One warm ``codex app-server`` process driven over JSON-RPC stdio."""

    def __init__(self, *, model: Optional[str] = None,
                 cwd: Optional[str] = None,
                 preamble: str = "",
                 reasoning_effort: str = "",
                 sandbox_mode: str = "workspace-write",
                 approval_policy: str = "never",
                 birkin_mcp: bool = False,
                 birkin_mcp_scope: str = "full",
                 startup_timeout: float = 90.0,
                 turn_timeout: float = 300.0,
                 request_timeout: float = 30.0):
        self.model = model
        self.cwd = cwd
        self.preamble = preamble
        # SECURITY: override the user's ~/.codex/config.toml so an exposed
        # gateway can't inherit sandbox_mode=danger-full-access + network.
        # Default is the safe cwd-scoped, no-network posture; approval_policy
        # 'never' means the model never gets to escalate (and the server won't
        # send approval requests we'd have to decline). Callers wanting full
        # host access opt in explicitly (e.g. an interactive REPL turn).
        self.sandbox_mode = sandbox_mode
        self.approval_policy = approval_policy
        # Attach birkin's OWN MCP server (memory, skills, propose_action) to
        # this codex child. Off by default: a session that carries the tools
        # must also answer their approval prompts, and only birkin's server is
        # ever answered — see _read_stdout.
        self.birkin_mcp = bool(birkin_mcp)
        self.birkin_mcp_scope = birkin_mcp_scope
        # Codex reasoning effort ("minimal"/"low"/"medium"/"high"). Empty =
        # the model default. A chat gateway wants fast replies, so a heavy
        # reasoning model (e.g. gpt-5.6-sol) is capped low here — cuts a
        # 7-20s warm turn to a few seconds.
        self.reasoning_effort = (reasoning_effort or "").strip()
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
        self._active_turn_id: Optional[str] = None
        self._interrupted = False
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
        if self.birkin_mcp:
            from .mcp_server import codex_config_args
            parts += codex_config_args(scope=self.birkin_mcp_scope)
        if self.reasoning_effort:
            if self.reasoning_effort not in (
                    "minimal", "low", "medium", "high", "xhigh"):
                raise CodexSessionError(
                    f"bad reasoning_effort: {self.reasoning_effort!r}")
            parts += ["-c",
                      f'model_reasoning_effort="{self.reasoning_effort}"']
        if self.sandbox_mode not in (
                "read-only", "workspace-write", "danger-full-access"):
            raise CodexSessionError(f"bad sandbox_mode: {self.sandbox_mode!r}")
        if self.approval_policy not in (
                "untrusted", "on-request", "on-failure", "never"):
            raise CodexSessionError(
                f"bad approval_policy: {self.approval_policy!r}")
        parts += ["-c", f'sandbox_mode="{self.sandbox_mode}"',
                  "-c", f'approval_policy="{self.approval_policy}"']
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
        try:  # register for the orphan reaper (procreg)
            from . import procreg
            procreg.register(self._proc.pid)
        except Exception:
            pass
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
        proc, self._proc = self._proc, None
        self._thread_id = None
        if proc is not None:
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()
            except OSError:
                pass
            if os.name == "nt":
                kill_tree(proc)
            else:
                try:
                    proc.terminate()
                except OSError:
                    pass
            try:
                proc.wait(timeout=3)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                try:
                    kill_tree(proc)
                    proc.wait(timeout=2)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    pass
            try:  # drop it from the orphan registry on graceful terminate
                from . import procreg
                procreg.unregister(proc.pid)
            except Exception:
                pass

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
                if method == "turn/start":
                    raise CodexTurnTimeout(f"{method} timed out")
                raise CodexSessionError(f"{method} timed out")
        finally:
            with self._replies_lock:
                self._replies.pop(rid, None)
        if "error" in msg:
            err = msg["error"] or {}
            raise CodexSessionError(
                f"{method} failed: {err.get('message')} ({err.get('code')})")
        return msg.get("result") or {}

    def _approval_result(self, msg: dict) -> dict:
        """How to answer one server-initiated approval ask.

        Accept ONLY an MCP elicitation from birkin's own server, and only when
        this session attached it. Everything else — exec, apply_patch, any
        other MCP server — declines, which is the pre-existing behaviour.
        """
        if self.birkin_mcp and msg.get("method") == _MCP_ELICITATION:
            params = msg.get("params") or {}
            if params.get("serverName") == _server_name():
                # MCP elicitation result shape, not codex's decision shape.
                # requestedSchema is an empty object for a tool-call ask.
                return {"action": "accept", "content": {}}
        return {"decision": "decline"}

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
                    # session never approves a WRITE it was asked to judge —
                    # exec commands and apply_patch are declined immediately,
                    # as before.
                    #
                    # The one exception is birkin's own MCP server, and only
                    # when this session deliberately attached it. Codex asks
                    # per tool call via an MCP elicitation:
                    #   method  mcpServer/elicitation/request
                    #   params  {serverName: "birkin", _meta:
                    #            {codex_approval_kind: "mcp_tool_call", ...}}
                    # Declining that is what made the gateway unable to
                    # remember anything: every memory_write_note came back as
                    # "user rejected MCP tool call", so a user asking birkin to
                    # remember a fact got a reply saying it could not.
                    #
                    # Approving is narrow and stays inside birkin's own gates:
                    # the exposed tools are memory (reversible files under the
                    # birkin home, already in auto_approve), skills (guard
                    # scanned) and propose_action — which QUEUES to the
                    # approvals inbox rather than executing. Any other MCP
                    # server, and every exec/apply_patch ask, still declines.
                    try:
                        self._send({"id": msg["id"],
                                    "result": self._approval_result(msg)})
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
            self._interrupted = False
            try:
                return self._turn(text, on_text, timeout)
            except CodexTurnTimeout:
                self._terminate(mark_closed=False)
                raise
            except CodexSessionError:
                if self._closed or self._interrupted:
                    # deliberately interrupted (process killed) — don't retry
                    # the cancelled turn; surface a clean marker.
                    if self._interrupted:
                        self._interrupted = False
                        return "⏹️ 중단했어요. 새 메시지로 진행할게요."
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
        ts = self.request("turn/start", {
            "threadId": self._thread_id,
            "input": [{"type": "text", "text": text}]})
        # Capture the turn id so interrupt() (called from ANOTHER thread while
        # this _turn blocks on the notes queue) can target turn/interrupt.
        turn_obj = ts.get("turn") if isinstance(ts, dict) else None
        self._active_turn_id = ((turn_obj or {}).get("id")
                                or (ts or {}).get("turnId")
                                if isinstance(ts, dict) else None)
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
                raise CodexTurnTimeout(
                    f"codex turn timed out after "
                    f"{timeout or self.turn_timeout:.0f}s")
            try:
                note = self._notes.get(timeout=remaining)
            except queue.Empty:
                raise CodexTurnTimeout("codex turn timed out")
            if note is None:
                if self._interrupted:
                    return "⏹️ 중단했어요. 새 메시지로 진행할게요."
                raise CodexSessionError("codex process exited unexpectedly")
            method = note.get("method") or ""
            params = note.get("params") or {}
            if method in ("item/completed", "turn/completed"):
                note_turn_id = params.get("turnId")
                if method == "turn/completed":
                    note_turn_id = (params.get("turn") or {}).get("id")
                if (params.get("threadId") != self._thread_id
                        or note_turn_id != self._active_turn_id):
                    continue
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
                self._active_turn_id = None
                if status and status not in ("completed", "interrupted"):
                    err = turn.get("error") or {}
                    return (f"[birkin] codex error: "
                            f"{str(err.get('message') or status)[:400]}")
                return final

    def interrupt(self) -> bool:
        """Cancel the in-flight turn (called from another thread — e.g. a new
        Telegram message arriving mid-turn).

        The app-server's ``turn/interrupt`` is unreliable on current codex
        (returns "no active turn" and can crash the process), so we stop the
        turn the way birkin's REPL stops a CLI turn: kill the process. The
        blocked ``_turn`` wakes on the closed pipe and returns cleanly (via
        the ``_interrupted`` flag) instead of retrying. Tradeoff: the codex
        thread context is lost, so the next message starts a fresh thread —
        acceptable for a deliberate "stop"."""
        if not self.is_alive():
            return False
        self._interrupted = True
        # Best-effort graceful interrupt first (harmless if it errors).
        try:
            if self._thread_id and self._active_turn_id:
                self.request("turn/interrupt",
                             {"threadId": self._thread_id,
                              "turnId": self._active_turn_id}, timeout=2)
        except CodexSessionError:
            pass
        if self.is_alive():        # still generating -> force stop
            try:
                kill_tree(self._proc)
            except Exception:
                pass
        return True


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
