from __future__ import annotations

from typing import cast

from birkin.native.projection import public_workspace_event
from birkin.workspace.records import WorkspaceEvent


def _event(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
    return WorkspaceEvent(
        protocol_version=1,
        session_id="session-1",
        cursor=1,
        event_id="event-1",
        type=event_type,
        timestamp="2026-08-17T00:00:00Z",
        actor_id="macos:window-main",
        command_id="command-1",
        payload=payload,
    )


def test_public_event_removes_integrity_and_secret_fields() -> None:
    secret = "seeded-native-secret"
    projected = public_workspace_event(
        _event(
            "command.accepted",
            {
                "command_type": "chat.send",
                "fingerprint": "internal-digest",
                "token": secret,
                "nested": {"authorization": secret},
            },
        )
    )

    rendered = str(projected)
    assert "fingerprint" not in rendered
    assert "internal-digest" not in rendered
    assert secret not in rendered
    assert projected["payload"] == {
        "command_type": "chat.send",
        "token": "[REDACTED]",
        "nested": {"authorization": "[REDACTED]"},
    }


def test_public_terminal_input_event_never_contains_typed_text() -> None:
    secret = "seeded-terminal-input"
    projected = public_workspace_event(
        _event(
            "terminal.input",
            {
                "terminal_id": "terminal-1",
                "sequence": 7,
                "text": secret,
            },
        )
    )

    assert secret not in str(projected)
    assert projected["payload"] == {
        "terminal_id": "terminal-1",
        "sequence": 7,
        "redacted": True,
    }


def test_public_error_is_bounded_without_traceback_or_secret() -> None:
    secret = "seeded-error-secret"
    projected = public_workspace_event(
        _event(
            "command.failed",
            {
                "error": "\n".join(
                    (
                        "Traceback (most recent call last):",
                        f"RuntimeError: api_key={secret}",
                        "x" * 500,
                    )
                )
            },
        )
    )

    payload = cast(dict[str, object], projected["payload"])
    error = str(payload["error"])
    assert len(error) <= 300
    assert "Traceback" not in error
    assert secret not in error
