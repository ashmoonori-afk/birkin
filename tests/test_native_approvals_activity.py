from __future__ import annotations

from pathlib import Path

import pytest

from birkin import store
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
