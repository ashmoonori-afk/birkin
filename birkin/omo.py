"""Trusted-channel slash-command control for local OMO sessions."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from .omo_rpc import OmoRpcClient, OmoState, RpcError


class Rpc(Protocol):
    """The OMO RPC operations exposed to the command controller."""

    def switch_session(self, path: Path) -> None: ...
    def prompt(self, message: str) -> str: ...
    def steer(self, message: str) -> None: ...
    def abort(self) -> None: ...
    def get_state(self) -> OmoState: ...
    def get_last_assistant_text(self) -> str | None: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class SessionInfo:
    session_id: str
    cwd: str
    path: Path
    modified_at: float


class OmoCommandError(ValueError):
    """The requested OMO command has invalid arguments."""


def parse_omo_command(text: str) -> tuple[str, str] | None:
    """Parse `/omo`, including Telegram's optional bot-name suffix."""
    words = text.strip().split(maxsplit=2)
    if not words or words[0].lower().split("@", 1)[0] != "/omo":
        return None
    command = words[1].lower() if len(words) > 1 else "help"
    argument = words[2].strip() if len(words) > 2 else ""
    return command, argument


def default_session_roots() -> tuple[Path, ...]:
    """Return the standard local OMO session directories."""
    base = Path.home() / ".senpi"
    roots = [base / "agent" / "sessions"]
    profiles = base / "profiles"
    if profiles.is_dir():
        roots.extend(profile / "agent" / "sessions" for profile in profiles.iterdir())
    return tuple(roots)


def list_sessions(roots: Sequence[Path], limit: int = 10) -> list[SessionInfo]:
    """Read recent OMO sessions without touching their contents."""
    candidates: list[tuple[float, Path]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.jsonl"):
            if "subagents" in {part.lower() for part in path.parts}:
                continue
            try:
                candidates.append((path.stat().st_mtime, path))
            except OSError:
                continue
    sessions: list[SessionInfo] = []
    for modified_at, path in sorted(candidates, reverse=True):
        try:
            with path.open(encoding="utf-8") as handle:
                header = json.loads(handle.readline())
            if header.get("type") != "session" or not header.get("id"):
                continue
            sessions.append(SessionInfo(str(header["id"]), str(header.get("cwd") or ""), path, modified_at))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if len(sessions) >= limit:
            break
    return sessions


class OmoController:
    """Select and control one local OMO session from a trusted chat."""

    HELP = ("OMO session control\n"
            "/omo list [count] - recent sessions\n"
            "/omo use <id-prefix> - select a session\n"
            "/omo send <prompt> - start a turn in the background\n"
            "/omo steer <message> - steer a running turn\n"
            "/omo abort - interrupt the running turn\n"
            "/omo status - inspect the selected session\n"
            "/omo last - show its latest assistant reply")

    def __init__(self, rpc: Rpc | None = None, session_roots: Sequence[Path] | None = None) -> None:
        self._rpc = rpc or OmoRpcClient()
        self._roots = tuple(session_roots) if session_roots is not None else default_session_roots()
        self._selected: SessionInfo | None = None
        self._operation_lock = threading.Lock()
        self._prompt_thread: threading.Thread | None = None
        self._prompt_error: str | None = None

    def handle(self, text: str) -> str:
        """Execute a fixed OMO command; free-form text never becomes shell input."""
        parsed = parse_omo_command(text)
        if parsed is None:
            return self.HELP
        command, argument = parsed
        try:
            if command in {"help", "commands"}:
                return self.HELP
            if command == "list":
                return self._list(argument)
            if command == "use":
                return self._use(argument)
            if self._selected is None and command in {"send", "steer", "abort", "stop", "interrupt", "status", "last"}:
                return "Select a session first with /omo use <id-prefix>."
            if command == "send":
                return self._send(argument)
            if command == "steer":
                if not argument:
                    return "Usage: /omo steer <message>"
                self._rpc.steer(argument)
                return "Steering message queued."
            if command in {"abort", "stop", "interrupt"}:
                self._rpc.abort()
                return "Abort requested."
            if command == "status":
                return self._status()
            if command == "last":
                return self._rpc.get_last_assistant_text() or "(No assistant reply yet.)"
            return f"Unknown OMO command: {command}\n\n{self.HELP}"
        except (OSError, RpcError, ValueError) as exc:
            return f"OMO error: {exc}"

    def _list(self, argument: str) -> str:
        limit = int(argument) if argument else 10
        if not 1 <= limit <= 20:
            raise OmoCommandError("list count must be between 1 and 20.")
        sessions = list_sessions(self._roots, limit)
        if not sessions:
            return "No OMO sessions found."
        rows = ["Recent OMO sessions:"]
        for session in sessions:
            marker = "*" if self._selected and self._selected.path == session.path else " "
            rows.append(f"{marker} {session.session_id}  {session.cwd}")
        return "\n".join(rows)

    def _use(self, prefix: str) -> str:
        if not prefix:
            return "Usage: /omo use <id-prefix>"
        matches = [session for session in list_sessions(self._roots, 200) if session.session_id.startswith(prefix)]
        if not matches:
            return f"No OMO session matches {prefix!r}."
        if len(matches) > 1:
            return f"{prefix!r} matches multiple OMO sessions; use a longer prefix."
        session = matches[0]
        with self._operation_lock:
            if self._prompt_thread is not None and self._prompt_thread.is_alive():
                return (
                    "Wait for the running OMO prompt to finish before "
                    "switching sessions."
                )
            self._rpc.switch_session(session.path)
            self._selected = session
        return f"Selected {session.session_id} ({session.cwd})."

    def _send(self, message: str) -> str:
        if not message:
            return "Usage: /omo send <prompt>"
        with self._operation_lock:
            if self._prompt_thread is not None and self._prompt_thread.is_alive():
                return "An OMO prompt is already running."
            self._prompt_error = None
            worker = threading.Thread(
                target=self._run_prompt,
                args=(message,),
                name="birkin-omo-prompt",
                daemon=True,
            )
            self._prompt_thread = worker
            worker.start()
        return (
            "OMO prompt started in the background. "
            "Use /omo status, /omo steer, /omo abort, or /omo last."
        )

    def _run_prompt(self, message: str) -> None:
        try:
            self._rpc.prompt(message)
        except (OSError, RpcError, ValueError) as exc:
            with self._operation_lock:
                self._prompt_error = str(exc)

    def _status(self) -> str:
        selected = self._selected
        if selected is None:
            return "Select a session first with /omo use <id-prefix>."
        state = self._rpc.get_state()
        with self._operation_lock:
            prompt_error = self._prompt_error
        status = (f"Session: {state.session_id or selected.session_id}\n"
                  f"CWD: {selected.cwd}\n"
                  f"Streaming: {state.is_streaming}")
        return f"{status}\nLast prompt error: {prompt_error}" if prompt_error else status

    def close(self) -> None:
        """Close the RPC process during gateway shutdown."""
        self._rpc.close()
