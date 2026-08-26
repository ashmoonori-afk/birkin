"""Terminal session ownership, sequencing, output, leases, and cleanup."""

from __future__ import annotations

import codecs
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import final

from .contracts import (
    REDACTION_MARKER, ProtocolError, TerminalLeaseRequired,
    TerminalSequenceRejected,
)
from .terminal_policy import (
    ApprovedTerminalLaunch, TerminalIdentity, TerminalInputIntent,
    TerminalResizeIntent, TerminalSignalIntent,
)
from .terminal_process import TerminalProcess, TerminalProcessFactory

TerminalEventSink = Callable[[str, dict[str, object]], object]
MAX_OUTPUT_BYTES = 16_384
MAX_SCREEN_BYTES = 65_536


@dataclass(slots=True)
class _TerminalSession:
    terminal_id: str
    process: TerminalProcess
    cwd: Path
    lease: str | None
    lease_expires_at: float
    columns: int
    rows: int
    decoder: codecs.IncrementalDecoder
    input_sequence: int = 0
    output_sequence: int = 0
    screen: bytearray = field(default_factory=bytearray)
    decoder_finalized: bool = False
    exited_emitted: bool = False


@final
class TerminalSessions:
    """Own all mutable terminal runtime state for one authority."""

    def __init__(
        self,
        session_id: str,
        emit: TerminalEventSink,
        process_factory: TerminalProcessFactory,
        monotonic: Callable[[], float] = time.monotonic,
        lease_ttl: float = 60.0,
    ) -> None:
        if lease_ttl <= 0 or lease_ttl > 300:
            raise ValueError("terminal lease TTL must be within 300 seconds")
        self._session_id = session_id
        self._emit = emit
        self._process_factory = process_factory
        self._monotonic = monotonic
        self._lease_ttl = lease_ttl
        self._sessions: dict[str, _TerminalSession] = {}
        self._lock = threading.RLock()

    @property
    def active_process_ids(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(
                session.process.pid
                for session in self._sessions.values()
                if session.process.poll() is None
            )

    def create(self, launch: ApprovedTerminalLaunch) -> dict[str, object]:
        process = self._process_factory(
            launch.shell, launch.cwd, launch.environment, 80, 24
        )
        terminal_id = f"terminal-{secrets.token_hex(12)}"
        lease = secrets.token_urlsafe(32)
        session = _TerminalSession(
            terminal_id=terminal_id,
            process=process,
            cwd=launch.cwd,
            lease=lease,
            lease_expires_at=self._monotonic() + self._lease_ttl,
            columns=80,
            rows=24,
            decoder=codecs.getincrementaldecoder("utf-8")(errors="replace"),
        )
        with self._lock:
            self._sessions[terminal_id] = session
        opened: dict[str, object] = {
            "terminal_id": terminal_id, "session_id": self._session_id,
            "actor_kind": "native_human", "cwd": str(launch.cwd),
            "shell": str(launch.shell), "pid": process.pid,
            "lease": lease, "lease_expires_in": self._lease_ttl,
            "state": "running", "columns": 80, "rows": 24,
        }
        _ = self._emit("terminal.opened", {**opened, "lease": REDACTION_MARKER})
        _ = self._refresh(session, 0.1)
        return opened

    def input(self, intent: TerminalInputIntent) -> dict[str, object]:
        session = self._live(intent.identity)
        if intent.sequence != session.input_sequence + 1:
            raise TerminalSequenceRejected(
                f"terminal input sequence must be {session.input_sequence + 1}"
            )
        session.process.write(intent.data, 1.0)
        session.input_sequence = intent.sequence
        _ = self._emit(
            "terminal.input",
            {
                "terminal_id": session.terminal_id,
                "sequence": intent.sequence,
                "redacted": True,
            },
        )
        output = self._refresh(session, 1.0)
        return {
            "terminal_id": session.terminal_id,
            "input_sequence": intent.sequence,
            "output_sequence": session.output_sequence, "output": output,
        }

    def resize(self, intent: TerminalResizeIntent) -> dict[str, object]:
        session = self._live(intent.identity)
        session.process.resize(intent.columns, intent.rows)
        session.columns, session.rows = intent.columns, intent.rows
        result: dict[str, object] = {
            "terminal_id": session.terminal_id,
            "columns": intent.columns, "rows": intent.rows,
        }
        _ = self._emit("terminal.resized", result)
        return result

    def signal(self, intent: TerminalSignalIntent) -> dict[str, object]:
        session = self._live(intent.identity)
        session.process.signal(intent.name)
        result: dict[str, object] = {
            "terminal_id": session.terminal_id, "signal": intent.name,
        }
        _ = self._emit("terminal.receipt", {**result, "action": "signal"})
        _ = self._refresh(session, 0.1)
        return result

    def close(self, identity: TerminalIdentity) -> dict[str, object]:
        session = self._live(identity)
        self._terminate(session, "closed")
        result: dict[str, object] = {
            "terminal_id": session.terminal_id, "closed": True,
        }
        _ = self._emit("terminal.receipt", {**result, "action": "close"})
        return result

    def snapshot(self, identity: TerminalIdentity) -> dict[str, object]:
        session = self._session(identity.terminal_id)
        _ = self._refresh(session, 0.0)
        status = session.process.poll()
        return {
            "terminal_id": session.terminal_id, "cwd": str(session.cwd),
            "screen": bytes(session.screen).decode("utf-8"),
            "output_sequence": session.output_sequence,
            "state": "exited" if status is not None else "running",
            "exit_status": status,
            "columns": session.columns, "rows": session.rows,
            "lease": None, "read_only": True,
        }

    def revoke_leases(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                session.lease = None

    def close_all(self) -> None:
        with self._lock:
            sessions = tuple(self._sessions.values())
        for session in sessions:
            self._terminate(session, "authority_closed", emit_exit=False)

    def _live(self, identity: TerminalIdentity) -> _TerminalSession:
        session = self._session(identity.terminal_id)
        if session.process.poll() is not None:
            _ = self._refresh(session, 0.1)
            raise TerminalLeaseRequired("terminal process has exited")
        if self._monotonic() >= session.lease_expires_at:
            self._terminate(session, "lease_expired")
            raise TerminalLeaseRequired("terminal lease expired")
        if (
            not identity.lease
            or session.lease is None
            or not secrets.compare_digest(identity.lease, session.lease)
        ):
            raise TerminalLeaseRequired("live terminal lease is required")
        return session

    def _session(self, terminal_id: str) -> _TerminalSession:
        with self._lock:
            session = self._sessions.get(terminal_id)
        if session is None:
            raise ProtocolError("terminal session was not found")
        return session

    def _refresh(self, session: _TerminalSession, timeout: float) -> str:
        deadline = self._monotonic() + timeout
        chunks = bytearray()
        while len(chunks) < MAX_OUTPUT_BYTES:
            wait = max(0.0, deadline - self._monotonic())
            chunk = session.process.read(MAX_OUTPUT_BYTES - len(chunks), wait)
            if not chunk:
                break
            chunks.extend(chunk)
        text = session.decoder.decode(bytes(chunks), final=False)
        if text:
            self._output(session, text)
        if session.process.poll() is not None:
            self._finalize(session)
            self._emit_exit(session)
        return text

    def _finalize(self, session: _TerminalSession) -> None:
        if session.decoder_finalized:
            return
        session.decoder_finalized = True
        final_text = session.decoder.decode(b"", final=True)
        if final_text:
            self._output(session, final_text)

    def _output(self, session: _TerminalSession, output: str) -> None:
        session.output_sequence += 1
        combined = bytes(session.screen) + output.encode("utf-8")
        if len(combined) > MAX_SCREEN_BYTES:
            combined = combined[-MAX_SCREEN_BYTES:].decode(
                "utf-8", errors="ignore"
            ).encode("utf-8")
        session.screen[:] = combined
        _ = self._emit(
            "terminal.output",
            {
                "terminal_id": session.terminal_id,
                "sequence": session.output_sequence, "data": output,
            },
        )

    def _terminate(
        self, session: _TerminalSession, reason: str, *, emit_exit: bool = True
    ) -> None:
        session.lease = None
        session.process.close(1)
        if not emit_exit:
            return
        _ = self._refresh(session, 0.0)
        self._finalize(session)
        self._emit_exit(session, reason)

    def _emit_exit(
        self, session: _TerminalSession, reason: str = "exited"
    ) -> None:
        status = session.process.poll()
        if status is None or session.exited_emitted:
            return
        session.exited_emitted = True
        session.lease = None
        _ = self._emit(
            "terminal.exited",
            {
                "terminal_id": session.terminal_id,
                "exit_status": status, "reason": reason,
            },
        )
