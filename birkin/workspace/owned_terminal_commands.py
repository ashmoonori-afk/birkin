"""Lease-bound command handlers for owned terminal sessions."""

from __future__ import annotations

import os
from typing import final

from .contracts import (
    ProtocolError,
    TerminalSequenceRejected,
    TerminalSignalRejected,
)
from .owned_terminal_pty import MAX_INPUT_BYTES, allowed_signals
from .owned_terminal_session import (
    TerminalSessionOwner,
    dimension,
    positive_integer,
    validate_keys,
)


@final
class TerminalCommands:
    """Execute terminal I/O commands against an owning session registry."""

    def __init__(self, sessions: TerminalSessionOwner) -> None:
        self._sessions = sessions

    def input(self, payload: dict[str, object]) -> dict[str, object]:
        validate_keys(
            payload,
            required={"terminal_id", "lease", "sequence", "data"},
            optional=set(),
        )
        session = self._sessions.live_session(payload, require_lease=True)
        sequence = positive_integer(payload["sequence"], "sequence")
        if sequence != session.input_sequence + 1:
            raise TerminalSequenceRejected(
                f"terminal input sequence must be {session.input_sequence + 1}"
            )
        data = payload["data"]
        if not isinstance(data, str):
            raise ProtocolError("terminal data must be a string")
        encoded = data.encode("utf-8")
        if not encoded or len(encoded) > MAX_INPUT_BYTES:
            raise ProtocolError(
                f"terminal input must be between 1 and {MAX_INPUT_BYTES} bytes"
            )
        session.write(encoded)
        session.input_sequence = sequence
        # Keystrokes are never durable; only their replay sequence is journaled.
        self._sessions.emit(
            "terminal.input",
            {
                "terminal_id": session.terminal_id,
                "sequence": sequence,
                "redacted": True,
            },
        )
        output = self._sessions.capture_output(session, timeout=1.0)
        self._sessions.emit_exit_if_needed(session)
        return {
            "terminal_id": session.terminal_id,
            "input_sequence": sequence,
            "output_sequence": session.output_sequence,
            "output": output.decode("utf-8", errors="replace"),
        }

    def resize(self, payload: dict[str, object]) -> dict[str, object]:
        validate_keys(
            payload,
            required={"terminal_id", "lease", "columns", "rows"},
            optional=set(),
        )
        session = self._sessions.live_session(payload, require_lease=True)
        columns = dimension(payload["columns"], "columns")
        rows = dimension(payload["rows"], "rows")
        session.pty.set_window_size(session.master_fd, columns, rows)
        result: dict[str, object] = {
            "terminal_id": session.terminal_id,
            "columns": columns,
            "rows": rows,
        }
        self._sessions.emit("terminal.resized", result)
        return result

    def signal(self, payload: dict[str, object]) -> dict[str, object]:
        validate_keys(
            payload,
            required={"terminal_id", "lease", "signal"},
            optional=set(),
        )
        session = self._sessions.live_session(payload, require_lease=True)
        signals = allowed_signals()
        signal_name = payload["signal"]
        if not isinstance(signal_name, str) or signal_name not in signals:
            raise TerminalSignalRejected("terminal signal must be INT, TERM, or HUP")
        os.killpg(session.process.pid, signals[signal_name])
        result: dict[str, object] = {
            "terminal_id": session.terminal_id,
            "signal": signal_name,
        }
        self._sessions.emit("terminal.receipt", {**result, "action": "signal"})
        self._sessions.emit_exit_if_needed(session)
        return result

    def close(self, payload: dict[str, object]) -> dict[str, object]:
        validate_keys(
            payload,
            required={"terminal_id", "lease"},
            optional=set(),
        )
        session = self._sessions.live_session(payload, require_lease=True)
        self._sessions.terminate(session, reason="closed")
        result: dict[str, object] = {
            "terminal_id": session.terminal_id,
            "closed": True,
        }
        self._sessions.emit("terminal.receipt", {**result, "action": "close"})
        return result

    def snapshot(self, payload: dict[str, object]) -> dict[str, object]:
        validate_keys(payload, required={"terminal_id"}, optional=set())
        session = self._sessions.session(payload["terminal_id"])
        _ = self._sessions.capture_output(session, timeout=0.0)
        self._sessions.emit_exit_if_needed(session)
        return {
            "terminal_id": session.terminal_id,
            "cwd": str(session.cwd),
            "screen": bytes(session.screen).decode("utf-8", errors="replace"),
            "output_sequence": session.output_sequence,
            "state": "exited" if session.process.poll() is not None else "running",
            "exit_status": session.process.poll(),
            "read_only": True,
        }
