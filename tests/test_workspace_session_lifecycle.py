from __future__ import annotations

from pathlib import Path

from birkin.workspace import WorkspaceCommand, WorkspaceHub


def _command(
    command_type: str,
    command_id: str,
    cursor: int,
    payload: dict[str, object],
) -> WorkspaceCommand:
    return WorkspaceCommand.parse(
        {
            "protocol_version": 1,
            "command_id": command_id,
            "expected_cursor": cursor,
            "type": command_type,
            "payload": payload,
            "client_context": {"surface": "macos", "view_id": "main"},
        }
    )


def test_session_select_records_event_and_changes_snapshot(tmp_path: Path) -> None:
    hub = WorkspaceHub(root=tmp_path, handlers={"chat.send": lambda _p: {}})
    first, _ = hub.create("first")
    _second, _ = hub.create("second")
    before = hub.snapshot()

    receipt = hub.select(
        _command("session.select", "select-1", before.cursor, {"session_id": "second"}),
        actor_id="macos:main",
    )

    assert receipt.state == "completed"
    assert hub.snapshot().session_id == "second"
    assert any(
        event.type == "session.selected"
        and event.payload == {"session_id": "second"}
        for event in first.events()
    )
    hub.close()
