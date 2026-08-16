from __future__ import annotations

import pytest

from birkin import approvals
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
