from __future__ import annotations

import pytest

from birkin import approvals, uistate
from birkin.workspace import WorkspaceEvent
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter


def test_approval_answer_event_carries_execution_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(
        event_type: str,
        payload: dict[str, object],
    ) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return WorkspaceEvent(
            protocol_version=1,
            session_id="receipt-session",
            cursor=1,
            event_id="event-1",
            type=event_type,
            timestamp="2026-08-16T00:00:00Z",
            actor_id="web:test",
            command_id="command-1",
            payload=payload,
        )

    def approve(_approval_id: str) -> str:
        return "exit 0: approved"

    monkeypatch.setattr(approvals, "approve", approve)
    adapter = RuntimeWorkspaceAdapter("receipt-session", emit)

    result = adapter.handlers()["approval.answer"](
        {"approval_id": "abc123def456", "decision": "approve"}
    )

    assert result == {"result": "exit 0: approved"}
    assert emitted == [
        (
            "approval.answered",
            {
                "approval_id": "abc123def456",
                "decision": "approve",
                "receipt": "exit 0: approved",
            },
        )
    ]


def _runtime_adapter() -> tuple[
    RuntimeWorkspaceAdapter,
    list[tuple[str, dict[str, object]]],
]:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(
        event_type: str,
        payload: dict[str, object],
    ) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return WorkspaceEvent(
            protocol_version=1,
            session_id="receipt-session",
            cursor=1,
            event_id="event-1",
            type=event_type,
            timestamp="2026-08-16T00:00:00Z",
            actor_id="web:test",
            command_id="command-1",
            payload=payload,
        )

    return RuntimeWorkspaceAdapter("receipt-session", emit), emitted


def test_tool_end_error_distinguishable_from_success() -> None:
    adapter, emitted = _runtime_adapter()

    adapter._runtime_event(
        "tool_end",
        {"name": "grep", "is_error": False, "content": "ok"},
    )
    adapter._runtime_event(
        "tool_end",
        {"name": "grep", "is_error": True, "content": "boom"},
    )

    assert [event_type for event_type, _payload in emitted] == [
        "tool.completed",
        "tool.failed",
    ]
    assert emitted[0][1]["state"] == "completed"
    assert emitted[1][1]["state"] == "failed"
    assert emitted[0][1] != emitted[1][1]


def test_aborted_tool_maps_failed() -> None:
    adapter, emitted = _runtime_adapter()

    adapter._runtime_event(
        "tool_end",
        {"content": "aborted", "is_error": True},
    )

    assert emitted[0][0] == "tool.failed"
    assert emitted[0][1]["state"] == "failed"


def test_all_emitted_states_in_uistate_vocabulary() -> None:
    adapter, emitted = _runtime_adapter()
    events = (
        "tool_start",
        "tool_end",
        "subagent.start",
        "subagent.done",
        "compact",
        "steer",
    )

    for event in events:
        adapter._runtime_event(event, {})
        adapter._runtime_event(event, {"is_error": True})
    adapter._runtime_event("no_such_event", {})

    for _event_type, payload in emitted:
        assert payload["state"] in uistate.UI_STATES


@pytest.mark.parametrize(
    ("payload", "expected_event_type", "expected_state"),
    [
        ({}, "tool.completed", "completed"),
        ({"is_error": None}, "tool.completed", "completed"),
        ({"is_error": 0}, "tool.completed", "completed"),
        ({"is_error": ""}, "tool.completed", "completed"),
        ({"is_error": False}, "tool.completed", "completed"),
        ({"is_error": True}, "tool.failed", "failed"),
        ({"is_error": 1}, "tool.failed", "failed"),
        ({"is_error": "false"}, "tool.failed", "failed"),
        ({"is_error": ["error"]}, "tool.failed", "failed"),
    ],
)
def test_tool_end_is_error_uses_truthiness(
    payload: dict[str, object],
    expected_event_type: str,
    expected_state: str,
) -> None:
    adapter, emitted = _runtime_adapter()

    adapter._runtime_event("tool_end", payload)

    assert emitted[0][0] == expected_event_type
    assert emitted[0][1]["state"] == expected_state


def test_event_type_table_pin() -> None:
    """Reverse the earlier pin after tool.failed consumer support was verified.

    Support exists in snapshot.py, workspace_terminal.py, and index.html.
    """
    adapter, emitted = _runtime_adapter()
    runtime_events = (
        ("tool_start", {}),
        ("tool_end", {}),
        ("tool_end", {"is_error": True}),
        ("subagent.start", {}),
        ("subagent.done", {}),
        ("compact", {}),
        ("steer", {}),
        ("no_such_event", {}),
    )

    for event, payload in runtime_events:
        adapter._runtime_event(event, payload)

    assert [event_type for event_type, _payload in emitted] == [
        "tool.started",
        "tool.completed",
        "tool.failed",
        "task.updated",
        "task.updated",
        "progress.updated",
        "progress.updated",
        "progress.updated",
    ]
