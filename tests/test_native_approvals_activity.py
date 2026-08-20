from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock

import pytest

from birkin import approvals, store
from birkin.workspace.records import WorkspaceEvent
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter
from birkin.workspace.service import WorkspaceService


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
        release.set()
        winner_result = winner.result(timeout=2)

    outcomes = [payload["outcome"] for kind, payload in emitted if kind == "approval.answered"]
    assert executions == 1
    assert sorted(outcomes) == ["answered_elsewhere", "approved"]
    assert loser_result == {"outcome": "answered_elsewhere", "approval_id": record["id"]}
    assert winner_result["outcome"] == "approved"
