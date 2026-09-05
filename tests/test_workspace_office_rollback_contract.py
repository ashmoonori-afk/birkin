"""office.rollback_request must survive contract parsing, not only dispatch."""

from __future__ import annotations

from pathlib import Path

from birkin.workspace import WorkspaceEvent
from birkin.workspace.contracts import WorkspaceCommand
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter


def _event(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
    return WorkspaceEvent(
        protocol_version=1,
        session_id="rollback-session",
        cursor=1,
        event_id="event-1",
        type=event_type,
        timestamp="2026-09-05T00:00:00Z",
        actor_id="actor-1",
        command_id="command-1",
        payload=payload,
    )


def test_office_rollback_request_parses_and_dispatches(tmp_path: Path) -> None:
    command = WorkspaceCommand.parse(
        {
            "protocol_version": 1,
            "command_id": "rollback-1",
            "expected_cursor": 0,
            "type": "office.rollback_request",
            "payload": {"receipt_ref": "job-1"},
            "client_context": {"surface": "windows", "view_id": "shell-1"},
        }
    )

    assert command.type == "office.rollback_request"
    assert command.payload == {"receipt_ref": "job-1"}

    adapter = RuntimeWorkspaceAdapter(
        "rollback-session", _event, workspace_root=tmp_path / "workspace"
    )
    assert command.type in adapter.handlers()
