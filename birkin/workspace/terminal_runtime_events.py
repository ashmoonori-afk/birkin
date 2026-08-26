"""Validated durable identities for unclaimed terminal runtime events."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ProtocolError, valid_identifier


@dataclass(frozen=True, slots=True)
class TerminalRuntimeEvent:
    actor_id: str
    command_id: str


def terminal_runtime_event(
    event_type: str,
    payload: dict[str, object],
) -> TerminalRuntimeEvent:
    """Parse the two event types allowed outside an active command receipt."""
    terminal_id = valid_identifier(payload.get("terminal_id"), "terminal_id")
    match event_type:
        case "terminal.output":
            sequence = payload.get("sequence")
            data = payload.get("data")
            if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
                raise ProtocolError("terminal runtime output sequence must be positive")
            if not isinstance(data, str):
                raise ProtocolError("terminal runtime output data must be a string")
            command_id = valid_identifier(
                f"{terminal_id}-output-{sequence}", "runtime command_id"
            )
        case "terminal.exited":
            status = payload.get("exit_status")
            reason = payload.get("reason")
            if isinstance(status, bool) or not isinstance(status, int):
                raise ProtocolError("terminal runtime exit status must be an integer")
            if not isinstance(reason, str):
                raise ProtocolError("terminal runtime exit reason must be a string")
            command_id = valid_identifier(
                f"{terminal_id}-exit", "runtime command_id"
            )
        case _:
            raise ProtocolError("workspace event emitted outside a command")
    return TerminalRuntimeEvent("runtime:terminal", command_id)
