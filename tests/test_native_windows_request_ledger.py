from __future__ import annotations

import socket
from pathlib import Path

import pytest

from birkin.native.protocol import NATIVE_PROTOCOL_NAME, NATIVE_PROTOCOL_VERSION, NativeEnvelope
from birkin.native.transport import receive_frame
from tests.native_windows_request_success import request_success
from tests.native_windows_terminal_bridge_support import WindowsTerminalBridgeHarness


def _event(cursor: int, event_type: str, command_id: str) -> NativeEnvelope:
    return NativeEnvelope(
        NATIVE_PROTOCOL_NAME,
        NATIVE_PROTOCOL_VERSION,
        "event",
        f"event-{cursor}",
        None,
        {"cursor": cursor, "type": event_type, "command_id": command_id, "payload": {}},
    )


def _error(
    command_id: str,
    code: str,
    *,
    accepted_cursor: int | None = None,
    result_event_cursor: int | None = None,
) -> NativeEnvelope:
    return NativeEnvelope(
        NATIVE_PROTOCOL_NAME,
        NATIVE_PROTOCOL_VERSION,
        "error",
        f"error-{command_id}",
        command_id,
        {
            "code": code,
            "message": code,
            **(
                {
                    "accepted_cursor": accepted_cursor,
                    "result_event_cursor": result_event_cursor,
                }
                if accepted_cursor is not None and result_event_cursor is not None
                else {}
            ),
        },
    )


def test_unexpected_pre_accept_error_fails_before_sentinel_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = WindowsTerminalBridgeHarness(tmp_path, auto_approve=True)
    client, server = socket.socketpair()
    harness.client = client
    harness.token = "token"
    harness.ledger.reset(20)
    def reject(_deadline: float) -> NativeEnvelope:
        return _error("must-succeed", "E_STALE_CURSOR")

    monkeypatch.setattr(harness, "_read", reject)
    sentinel_waited = False
    try:
        with pytest.raises(AssertionError, match="code=E_STALE_CURSOR") as raised:
            _ = request_success(harness, "terminal.input", "must-succeed", {"sequence": 2})
            sentinel_waited = True
        assert "submitted_expected_cursor=20" in str(raised.value)
        assert "input_sequence=2" in str(raised.value)
        assert sentinel_waited is False
        _ = receive_frame(server)
    finally:
        client.close()
        server.close()


def test_accepted_error_waits_for_failed_cursor_before_next_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = WindowsTerminalBridgeHarness(tmp_path, auto_approve=True)
    client, server = socket.socketpair()
    harness.client = client
    harness.token = "token"
    harness.ledger.reset(10)
    frames = [
        _error(
            "failed-command",
            "E_TERMINAL_SEQUENCE",
            accepted_cursor=11,
            result_event_cursor=14,
        ),
        _event(11, "command.accepted", "failed-command"),
        _event(12, "command.started", "failed-command"),
        _event(13, "terminal.receipt", "failed-command"),
        _event(14, "command.failed", "failed-command"),
        _error("next-command", "E_PRE_ACCEPT"),
    ]

    def read(_deadline: float) -> NativeEnvelope:
        message = frames.pop(0)
        if message.kind == "event":
            harness.ledger.record(message)
        return message

    monkeypatch.setattr(harness, "_read", read)
    try:
        response, _ = harness.request("terminal.input", "failed-command", {})
        assert response.body["code"] == "E_TERMINAL_SEQUENCE"
        assert harness.current_cursor == 14
        first = receive_frame(server)
        first_command = first.body.get("command")
        assert isinstance(first_command, dict)
        assert first_command["expected_cursor"] == 10
        pre_accept, _ = harness.request("terminal.input", "next-command", {})
        assert pre_accept.body["code"] == "E_PRE_ACCEPT"
        second = receive_frame(server)
        second_command = second.body.get("command")
        assert isinstance(second_command, dict)
        assert second_command["expected_cursor"] == 14
    finally:
        client.close()
        server.close()
