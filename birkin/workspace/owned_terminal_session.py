"""Terminal session registry, leases, output events, and cleanup."""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from typing import final

from .contracts import ProtocolError, TerminalLeaseRequired
from .owned_terminal_pty import TerminalSession

TerminalEventSink = Callable[[str, dict[str, object]], object]


@final
class TerminalSessionOwner:
    """Own mutable terminal sessions and their lease-bound lifecycle."""

    def __init__(
        self,
        emit: TerminalEventSink,
        monotonic: Callable[[], float],
    ) -> None:
        self._emit = emit
        self._monotonic = monotonic
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = threading.RLock()

    @property
    def active_process_ids(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(
                session.process.pid
                for session in self._sessions.values()
                if session.process.poll() is None
            )

    def register(self, session: TerminalSession) -> None:
        with self._lock:
            self._sessions[session.terminal_id] = session

    def emit(self, kind: str, payload: dict[str, object]) -> None:
        _ = self._emit(kind, payload)

    def capture_output(self, session: TerminalSession, *, timeout: float) -> str:
        pieces: list[str] = []

        def consume(output: bytes, final: bool) -> None:
            projected = session.record_output(output, final=final)
            data = projected["data"]
            if isinstance(data, str) and data:
                pieces.append(data)
                self.emit("terminal.output", projected)

        _output, _reached_eof = session.pump_output(
            timeout=timeout,
            consume=consume,
        )
        return "".join(pieces)

    def live_session(
        self,
        payload: dict[str, object],
        *,
        require_lease: bool,
    ) -> TerminalSession:
        session = self.session(payload["terminal_id"])
        if session.process.poll() is not None:
            if not session.released:
                _ = self.capture_output(session, timeout=0.0)
            self.emit_exit_if_needed(session)
            raise TerminalLeaseRequired("terminal process has exited")
        if require_lease:
            lease = payload.get("lease")
            if self._monotonic() >= session.lease_expires_at:
                self.terminate(session, reason="lease_expired")
                raise TerminalLeaseRequired("terminal lease expired")
            if (
                not isinstance(lease, str)
                or not lease
                or session.lease is None
                or not secrets.compare_digest(lease, session.lease)
            ):
                raise TerminalLeaseRequired("live terminal lease is required")
        return session

    def session(self, terminal_id: object) -> TerminalSession:
        if not isinstance(terminal_id, str):
            raise ProtocolError("terminal_id must be a string")
        with self._lock:
            session = self._sessions.get(terminal_id)
        if session is None:
            raise ProtocolError("terminal session was not found")
        return session

    def revoke_leases(self) -> None:
        with self._lock:
            sessions = tuple(self._sessions.values())
        for session in sessions:
            session.lease = None

    def close_all(self) -> None:
        with self._lock:
            sessions = tuple(self._sessions.values())
        for session in sessions:
            self.terminate(session, reason="authority_closed", emit_exit=False)

    def terminate(
        self,
        session: TerminalSession,
        *,
        reason: str,
        emit_exit: bool = True,
    ) -> None:
        try:
            session.terminate_process()
            if emit_exit:
                _ = self.capture_output(session, timeout=0.0)
                self.emit_exit_if_needed(session, reason=reason)
        finally:
            session.release()

    def backend_failed(self, session: TerminalSession) -> None:
        """Failure-atomically tear down a terminal after an OS mutation error."""
        self.terminate(session, reason="backend_failure")

    def emit_exit_if_needed(
        self,
        session: TerminalSession,
        *,
        reason: str = "exited",
    ) -> None:
        status = session.process.poll()
        if status is None or session.exited_emitted:
            return
        session.exited_emitted = True
        try:
            self.emit(
                "terminal.exited",
                {
                    "terminal_id": session.terminal_id,
                    "exit_status": status,
                    "reason": reason,
                },
            )
        finally:
            session.release()


def validate_keys(
    payload: dict[str, object],
    *,
    required: set[str],
    optional: set[str],
) -> None:
    if not required <= set(payload) or set(payload) - required - optional:
        raise ProtocolError("terminal payload keys do not match the contract")


def positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProtocolError(f"terminal {label} must be a positive integer")
    return value


def dimension(value: object, label: str) -> int:
    result = positive_integer(value, label)
    if result > 1_000:
        raise ProtocolError(f"terminal {label} exceeds 1000")
    return result
