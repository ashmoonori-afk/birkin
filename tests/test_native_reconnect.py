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
