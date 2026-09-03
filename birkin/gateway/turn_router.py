"""Thin coordinator for typed gateway turn stages."""

from __future__ import annotations

from .turn_admission import admit_turn
from .turn_commands import dispatch_command_or_acquire
from .turn_completion import release_turn
from .turn_model import run_model_turn
from .turn_types import (
    Admitted,
    CommandReply,
    GatewayTurn,
    ProgressCallback,
    TextCallback,
)


def route_turn(
    gateway: GatewayTurn,
    channel: str,
    chat_id: str,
    text: str,
    on_text: TextCallback = None,
    workflow_id: str | None = None,
    on_progress: ProgressCallback = None,
    sender_id: str | None = None,
) -> str:
    """Coordinate admission, command dispatch, and a model turn."""
    admission = admit_turn(gateway, channel, chat_id, text, sender_id)
    if not isinstance(admission, Admitted):
        return admission.reply
    request = admission.request

    command = dispatch_command_or_acquire(gateway, request)
    if isinstance(command, CommandReply):
        return command.reply
    lease = command.lease

    try:
        return run_model_turn(
            gateway, request, lease, on_text, workflow_id, on_progress
        )
    finally:
        release_turn(gateway, request.key, lease)
