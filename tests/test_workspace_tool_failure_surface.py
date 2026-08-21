from __future__ import annotations

from birkin.workspace import WorkspaceEvent
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter
from birkin.workspace.snapshot import _panel_item


def test_tool_end_failure_reaches_rendered_panel_state() -> None:
    emitted: list[WorkspaceEvent] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        event = WorkspaceEvent(
            protocol_version=1,
            session_id="surface-session",
            cursor=len(emitted) + 1,
            event_id=f"event-{len(emitted) + 1}",
            type=event_type,
            timestamp="2026-08-21T00:00:00Z",
            actor_id="web:test",
            command_id="command-1",
            payload=payload,
        )
        emitted.append(event)
        return event

    adapter = RuntimeWorkspaceAdapter("surface-session", emit)
    adapter._runtime_event("tool_end", {"name": "read", "is_error": False})
    adapter._runtime_event("tool_end", {"name": "read", "is_error": True})

    panel_items = [_panel_item(event) for event in emitted]

    assert [item["ui_state"] for item in panel_items] == ["succeeded", "failed"]
