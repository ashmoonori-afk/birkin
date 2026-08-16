"""Public ToolRegistry -> workspace reducer -> OS adapter contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from birkin.tools import ToolContext, build_registry
from birkin.tools.computer_use import _service
from birkin.workspace import WorkspaceEvent
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter
from tests.computer_use_fakes import FakeBackend


def test_registry_routes_computer_use_events_into_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    emitted: list[WorkspaceEvent] = []

    def emit(kind: str, payload: dict[str, object]) -> WorkspaceEvent:
        event = WorkspaceEvent(
            protocol_version=1,
            session_id="computer-e2e",
            cursor=len(emitted) + 1,
            event_id=f"event-{len(emitted) + 1}",
            type=kind,
            timestamp="2026-08-16T00:00:00Z",
            actor_id="e2e",
            command_id="e2e-command",
            payload=payload,
        )
        emitted.append(event)
        return event

    workspace = RuntimeWorkspaceAdapter("computer-e2e", emit)
    context = ToolContext(
        cfg={
            "desktop_tools": True,
            "session_id": "computer-e2e",
            "computer_use": {
                "enabled": True,
                "allowed_apps": ["org.birkin.QAFixture"],
            },
        },
        client=None,
        cwd=tmp_path,
        emit=workspace._runtime_event,
    )
    service = _service(context)
    service.backend = FakeBackend()
    registry = build_registry(context)

    apps_result = registry.execute(
        "computer_use",
        {"version": 1, "action": "list_apps"},
    )
    apps = json.loads(str(apps_result.content))
    windows_result = registry.execute(
        "computer_use",
        {
            "version": 1,
            "action": "list_windows",
            "session_id": "computer-e2e",
            "app_ref": apps["apps"][0]["app_ref"],
        },
    )
    windows = json.loads(str(windows_result.content))
    result = registry.execute(
        "computer_use",
        {
            "version": 1,
            "action": "capture",
            "session_id": "computer-e2e",
            "mode": "ax",
            "target": {
                "window_ref": windows["windows"][0]["window_ref"],
            },
        },
    )

    assert result.is_error is False
    assert json.loads(str(result.content))["snapshot_ref"]
    assert emitted[-1].type == "computer.updated"
