"""Structural contract tests for immutable gateway stage messages."""

from __future__ import annotations

import threading
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from birkin.gateway.turn_types import (
    Admitted,
    CommandReply,
    ModelLease,
    PreparedTurn,
    Rejected,
    TurnLease,
    TurnRequest,
)


def _request() -> TurnRequest:
    return TurnRequest(
        channel="http",
        chat_id="chat",
        text="/neurosis idea",
        key=("http", "chat"),
        session_id="gateway-http-id",
        command="neurosis",
        command_arg="idea",
        display_text="/neurosis idea",
        skill_query="/neurosis idea",
    )


def test_stage_messages_are_slotted_immutable_values() -> None:
    request = _request()
    normalized = replace(
        request,
        text="kickoff",
        command=None,
        display_text="idea",
        skill_query="neurosis idea",
    )
    lease = TurnLease(False, False, object(), threading.Event(), None)
    prepared = PreparedTurn("kickoff", False, False, {}, lambda _info: None)
    messages = (
        request,
        normalized,
        lease,
        prepared,
        Admitted(normalized),
        Rejected("denied"),
        CommandReply("done"),
        ModelLease(lease),
    )

    assert request.command == "neurosis"
    assert normalized.command is None
    for message in messages:
        assert hasattr(type(message), "__slots__")
        with pytest.raises(FrozenInstanceError):
            setattr(message, fields(message)[0].name, None)
