from __future__ import annotations

from typing import cast

from birkin.native.projection import (
    public_error_text,
    public_native_mapping,
    public_workspace_event,
)
from birkin.workspace.records import WorkspaceEvent

_SEEDED_SECRET = "Bearer SEEDED_PUBLIC_SECRET"


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


def test_public_terminal_output_preserves_vt_stream_without_secret_redaction_regression() -> None:
    # Given
    raw_prefix = "".join((
        "\x1b[?90",
        "01h\r\n\x1b]0;terminal-title\x07한글-日本語 <>& ",
    ))
    projected_event = _event(
        "terminal.output",
        {
            "terminal_id": "terminal-raw-vt-73",
            "sequence": 9,
            "data": raw_prefix + _SEEDED_SECRET + "\n" + ("x" * 25_000),
            "lease": "must-not-project",
            "unexpected": "must-not-project",
        },
    )

    # When
    projected = public_workspace_event(projected_event)

    # Then
    payload = cast(dict[str, object], projected["payload"])
    data = str(payload["data"])
    assert data.startswith(raw_prefix + "[REDACTED]\n")
    assert len(data) == 20_000
    assert _SEEDED_SECRET not in data
    assert payload.keys() == {"terminal_id", "sequence", "data"}
    assert payload["terminal_id"] == "terminal-raw-vt-73"
    assert payload["sequence"] == 9


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


def test_public_event_redacts_seeded_secret_in_ordinary_string() -> None:
    projected = public_workspace_event(
        _event(
            "activity.recorded",
            {"note": _SEEDED_SECRET},
        )
    )

    assert _SEEDED_SECRET not in str(projected)
    assert "[REDACTED]" in str(projected)


def test_public_error_text_redacts_seeded_bearer_secret() -> None:
    projected = public_error_text(f"request failed: {_SEEDED_SECRET}")

    assert _SEEDED_SECRET not in projected
    assert "[REDACTED]" in projected


def test_public_snapshot_mapping_redacts_nested_seeded_secret() -> None:
    projected = public_native_mapping(
        {
            "conversation": [
                {"role": "assistant", "text": _SEEDED_SECRET},
            ],
            "status": {"connection": "connected"},
        }
    )

    assert _SEEDED_SECRET not in str(projected)
    assert "[REDACTED]" in str(projected)


def test_reduced_snapshot_treats_a_redacted_lease_as_no_lease() -> None:
    """Given a journal event whose lease was redacted, When the canonical
    snapshot is reduced, Then the terminal carries no lease and stays
    read-only."""
    from birkin.workspace.contracts import REDACTION_MARKER
    from birkin.workspace.records import WorkspaceEvent
    from birkin.workspace.snapshot import reduce_snapshot

    opened = WorkspaceEvent(
        protocol_version=1,
        session_id="session-1",
        cursor=1,
        event_id="event-1",
        type="terminal.opened",
        timestamp="2026-08-20T12:00:00Z",
        actor_id="macos:main",
        command_id="command-1",
        payload={
            "terminal_id": "terminal-1",
            "cwd": "/private/workspace",
            "lease": REDACTION_MARKER,
            "state": "running",
        },
    )

    snapshot = reduce_snapshot("session-1", (opened,))

    terminals = snapshot.to_json()["terminals"]
    assert isinstance(terminals, list)
    terminal = cast(dict[str, object], terminals[0])
    assert isinstance(terminal, dict)
    assert terminal["lease"] is None
    assert terminal["read_only"] is True
