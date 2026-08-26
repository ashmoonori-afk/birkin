from __future__ import annotations

from pathlib import Path

from birkin.native.session import NativeProjectionSession
from birkin.workspace import WorkspaceCommand, WorkspaceService


def _command(*, command_id: str, cursor: int, text: str) -> WorkspaceCommand:
    return WorkspaceCommand.parse(
        {
            "protocol_version": 1,
            "command_id": command_id,
            "expected_cursor": cursor,
            "type": "chat.send",
            "payload": {"text": text},
            "client_context": {"surface": "macos", "view_id": "main"},
        }
    )


def _service(tmp_path: Path) -> WorkspaceService:
    return WorkspaceService(
        root=tmp_path,
        session_id="session-1",
        handlers={"chat.send": lambda payload: {"reply": str(payload["text"])}},
    )


def test_reconnect_snapshot_preserves_bounded_terminal_vt_screen_without_weakening_generic_redaction() -> None:
    # Given
    from typing import cast

    from birkin.workspace.records import (
        ComposerState,
        WorkspaceEvent,
        WorkspaceSnapshot,
        WorkspaceStatus,
    )

    secret = "Bearer SEEDED_RECONNECT_SECRET"
    raw_controls = (
        "\x1b[?9001h\x1b[?1004h\x1b[2J\x1b[H\x1b[31m"
        "\x1b]0;C:\\Users\\owner\\python.exe\x07"
        "한글-日本語 <>&\r\n"
    )
    expected_meaningful = raw_controls + "[REDACTED] terminal-tail"
    suffix = ("x" * (65_535 - len(expected_meaningful))) + expected_meaningful
    raw_screen = "P\udc00" + ("x" * (65_535 - len(expected_meaningful))) + raw_controls + secret + " terminal-tail"
    generic_text = "\x1b[?9001h <>& " + secret
    snapshot = WorkspaceSnapshot(
        protocol_version=1,
        session_id="session-1",
        cursor=9,
        panels=(),
        conversation=({"role": "assistant", "text": generic_text},),
        composer=ComposerState(can_send=True),
        status=WorkspaceStatus(connection="connected"),
        working_memory={},
        approval_policy={},
        terminals=({
            "terminal_id": "terminal-reconnect-73",
            "cwd": r"C:\Users\owner\workspace",
            "screen": raw_screen,
            "output_sequence": 7,
            "state": "running",
            "exit_status": None,
            "columns": 100,
            "rows": 30,
            "lease": "transient-must-not-project",
            "read_only": False,
        },),
    )

    class FrozenSource:
        def snapshot(self) -> WorkspaceSnapshot:
            return snapshot

        def events(self, *, after: int = 0) -> tuple[WorkspaceEvent, ...]:
            _ = after
            return ()

    projection = NativeProjectionSession(FrozenSource(), instance_id="instance-1")

    # When
    batch = projection.subscribe(after_cursor=0, known_instance_id=None)

    # Then
    assert batch.snapshot is not None
    terminals = batch.snapshot["terminals"]
    assert isinstance(terminals, list)
    terminal_value = cast(list[object], terminals)[0]
    assert isinstance(terminal_value, dict)
    terminal = cast(dict[str, object], terminal_value)
    screen = terminal["screen"]
    assert isinstance(screen, str)
    assert secret not in screen
    assert screen == suffix
    assert len(screen) == 65_535
    assert not screen.startswith("\udc00")
    assert "\x1b[?9001h\x1b[?1004h" in screen
    assert "\x1b]0;C:\\Users\\owner\\python.exe\x07" in screen
    assert "한글-日本語 <>&\r\n" in screen
    assert "[REDACTED]" in screen
    assert terminal["lease"] is None
    assert terminal["read_only"] is True
    conversation = batch.snapshot["conversation"]
    assert isinstance(conversation, list)
    message_value = cast(list[object], conversation)[0]
    assert isinstance(message_value, dict)
    message = cast(dict[str, object], message_value)
    generic = message["text"]
    assert isinstance(generic, str)
    assert "\x1b" not in generic
    assert "&lt;&gt;&amp;" in generic
    assert secret not in generic
    assert "[REDACTED]" in generic


def test_initial_subscription_returns_snapshot(tmp_path: Path) -> None:
    projection = NativeProjectionSession(
        _service(tmp_path),
        instance_id="instance-1",
    )

    batch = projection.subscribe(
        after_cursor=0,
        known_instance_id=None,
    )

    assert batch.instance_id == "instance-1"
    assert batch.snapshot is not None
    assert batch.snapshot["cursor"] == 0
    assert batch.events == ()


def test_reconnect_replays_only_events_after_cursor(tmp_path: Path) -> None:
    service = _service(tmp_path)
    projection = NativeProjectionSession(service, instance_id="instance-1")
    initial = projection.subscribe(after_cursor=0, known_instance_id=None)
    assert initial.snapshot is not None
    initial_cursor = initial.snapshot["cursor"]
    assert isinstance(initial_cursor, int)
    _ = service.submit(
        _command(command_id="send-1", cursor=0, text="hello"),
        actor_id="macos:main",
    )

    batch = projection.subscribe(
        after_cursor=initial_cursor,
        known_instance_id="instance-1",
    )

    assert batch.snapshot is None
    assert batch.events
    assert [event["cursor"] for event in batch.events] == list(
        range(1, len(batch.events) + 1)
    )


def test_instance_change_forces_full_snapshot(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _ = service.submit(
        _command(command_id="send-1", cursor=0, text="hello"),
        actor_id="macos:main",
    )
    projection = NativeProjectionSession(service, instance_id="instance-2")

    batch = projection.subscribe(
        after_cursor=1,
        known_instance_id="instance-1",
    )

    assert batch.snapshot is not None
    assert batch.snapshot["cursor"] == service.snapshot().cursor
    assert batch.events == ()
    assert batch.reset_reason == "instance_changed"


def test_cursor_ahead_of_server_forces_full_snapshot(tmp_path: Path) -> None:
    projection = NativeProjectionSession(
        _service(tmp_path),
        instance_id="instance-1",
    )

    batch = projection.subscribe(
        after_cursor=999,
        known_instance_id="instance-1",
    )

    assert batch.snapshot is not None
    assert batch.reset_reason == "cursor_ahead"
