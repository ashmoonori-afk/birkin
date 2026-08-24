from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Event, Lock

import pytest

from birkin import approvals, config, store
from birkin.workspace.records import WorkspaceEvent
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter
from birkin.workspace.service import WorkspaceService
from birkin.workspace.snapshot import reduce_snapshot


def _approval_items(service: WorkspaceService) -> list[dict[str, object]]:
    panel = next(panel for panel in service.snapshot().panels if panel.key == "approvals")
    return list(panel.items)


def test_snapshot_projects_pending_risk_and_sealed_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    record = store.add_pending(
        pending_id="abc123def456",
        category="operation",
        title="Write release manifest",
        description="Write one digest-bound file",
        payload={"operation": {"kind": "write"}, "digest": "a" * 64},
        origin="test",
    )
    service = WorkspaceService(root=tmp_path / "journal", session_id="session-1", handlers={})

    item = next(item for item in _approval_items(service) if item["id"] == record["id"])

    assert item["status"] == "pending"
    assert item["risk"] == "high"
    assert item["sealed"] is True
    assert item["decided"] is False
    assert item["ui_state"] == "action_needed"


def test_live_approval_event_preserves_risk_and_sealed_state() -> None:
    event = WorkspaceEvent(
        protocol_version=1, session_id="session-1", cursor=1,
        event_id="approval-event", type="approval.requested",
        timestamp="2026-08-20T00:00:00Z", actor_id="python",
        command_id="command-1", payload={
            "approval_id": "abc123def456", "summary": "Write manifest",
            "description": "Digest-bound write", "category": "operation",
            "status": "pending", "risk": "high", "sealed": True,
            "decided": False,
        },
    )

    snapshot = reduce_snapshot("session-1", (event,))
    item = next(panel.items[0] for panel in snapshot.panels if panel.key == "approvals")

    assert item["risk"] == "high"
    assert item["sealed"] is True
    assert item["decided"] is False
    assert item["category"] == "operation"


def test_snapshot_reconciles_answered_approval_without_losing_request_details() -> None:
    requested = WorkspaceEvent(
        protocol_version=1, session_id="session-1", cursor=1,
        event_id="approval-requested", type="approval.requested",
        timestamp="2026-08-20T00:00:00Z", actor_id="python",
        command_id="command-1", payload={
            "approval_id": "abc123def456", "summary": "Write manifest",
            "description": "Digest-bound write", "category": "operation",
            "status": "pending", "risk": "high", "sealed": True,
            "decided": False,
        },
    )
    answered = WorkspaceEvent(
        protocol_version=1, session_id="session-1", cursor=2,
        event_id="approval-answered", type="approval.answered",
        timestamp="2026-08-20T00:00:01Z", actor_id="python",
        command_id="command-2", payload={
            "approval_id": "abc123def456", "decision": "approve",
            "outcome": "approved", "receipt": "exit 0: approved",
        },
    )

    snapshot = reduce_snapshot("session-1", (requested, answered))
    approvals = next(
        panel.items for panel in snapshot.panels if panel.key == "approvals"
    )

    assert len(approvals) == 1
    assert approvals[0] == {
        "id": "abc123def456",
        "summary": "Write manifest",
        "status": "approved",
        "cursor": 2,
        "kind": "approval",
        "ui_state": "succeeded",
        "description": "Digest-bound write",
        "category": "operation",
        "risk": "high",
        "sealed": True,
        "decided": True,
        "receipt_ref": "exit 0: approved",
    }


def test_two_surfaces_resolve_one_approval_with_answered_elsewhere_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    record = store.add_pending(
        pending_id="def456abc123", category="shell", title="Run once",
        description="One execution", payload={"command": "true"}, origin="test",
    )
    executing = Event()
    release = Event()
    executions = 0
    execution_lock = Lock()

    def execute(_category: str, _payload: dict[str, object]) -> str:
        nonlocal executions
        with execution_lock:
            executions += 1
        executing.set()
        assert release.wait(timeout=2), "race execution was not released"
        return "executed"

    monkeypatch.setattr(approvals, "execute_action", execute)
    emitted: list[tuple[str, dict[str, object]]] = []
    emitted_lock = Lock()

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        with emitted_lock:
            emitted.append((event_type, payload))
            cursor = len(emitted)
        return WorkspaceEvent(
            protocol_version=1, session_id="session-1", cursor=cursor,
            event_id=f"event-{cursor}", type=event_type,
            timestamp="2026-08-20T00:00:00Z", actor_id="test",
            command_id=f"command-{cursor}", payload=payload,
        )

    adapter = RuntimeWorkspaceAdapter("session-1", emit)
    handler = adapter.handlers()["approval.answer"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        winner = pool.submit(handler, {"approval_id": record["id"], "decision": "approve"})
        assert executing.wait(timeout=2), "approval execution did not start"
        loser = pool.submit(handler, {"approval_id": record["id"], "decision": "approve"})
        loser_result = loser.result(timeout=2)
        _ = release.set()
        winner_result = winner.result(timeout=2)

    outcomes = [
        str(payload["outcome"])
        for kind, payload in emitted
        if kind == "approval.answered"
    ]
    assert executions == 1
    assert sorted(outcomes) == ["answered_elsewhere", "approved"]
    assert loser_result == {"outcome": "answered_elsewhere", "approval_id": record["id"]}
    assert winner_result["outcome"] == "approved"


def test_snapshot_distinguishes_requested_effective_policy_and_pending_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    _ = config.config_path().write_text(
        json.dumps({"auto_approve": "shell"}), encoding="utf-8"
    )
    record = store.add_pending(
        pending_id="fed123abc456", category="shell", title="Pending shell",
        description="Awaiting a human", payload={"command": "true"}, origin="test",
    )
    service = WorkspaceService(root=tmp_path / "journal", session_id="session-1", handlers={})

    policy = service.snapshot().approval_policy

    assert policy["requested"] == {"auto_approve": "shell"}
    assert policy["effective"] == {"auto_approve": ["memory", "skill"]}
    assert policy["pending_requests"] == [record["id"]]


def test_activity_projection_appends_receipts_and_integrity_warnings() -> None:
    events = (
        WorkspaceEvent(
            protocol_version=1, session_id="session-1", cursor=1,
            event_id="receipt-1", type="receipt.recorded",
            timestamp="2026-08-20T00:00:00Z", actor_id="python",
            command_id="command-1",
            payload={"receipt_ref": "receipt:command-1", "summary": "Command completed"},
        ),
        WorkspaceEvent(
            protocol_version=1, session_id="session-1", cursor=2,
            event_id="warning-1", type="integrity.warning",
            timestamp="2026-08-20T00:00:01Z", actor_id="python",
            command_id="command-2",
            payload={"summary": "Interrupted receipt sealed", "status": "warning"},
        ),
        WorkspaceEvent(
            protocol_version=1, session_id="session-1", cursor=3,
            event_id="receipt-2", type="receipt.recorded",
            timestamp="2026-08-20T00:00:02Z", actor_id="python",
            command_id="command-3",
            payload={"receipt_ref": "receipt:command-3", "summary": "Second command completed"},
        ),
    )

    snapshot = reduce_snapshot("session-1", events)
    activity = next(panel.items for panel in snapshot.panels if panel.key == "activity_logs")

    assert [item["id"] for item in activity] == ["receipt-1", "warning-1", "receipt-2"]
    assert [item["kind"] for item in activity] == [
        "receipt", "integrity_warning", "receipt",
    ]
    assert [item["cursor"] for item in activity] == [1, 2, 3]
