from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import cast

from birkin import approvals, work_items
from birkin.office.meeting_actions import review_meeting_actions
from birkin.workspace.service import WorkspaceService


def test_confirmed_meeting_items_persist_with_unknowns_and_source(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    draft = review_meeting_actions(
        "민지는 견적을 확인한다. 기한은 미정이다.",
        [{"action": "견적 확인", "evidence": "민지는 견적을 확인한다.", "assignee": "민지"}],
    )
    payload = {
        "action": "confirm_meeting",
        "draft_sha256": draft["draft_sha256"],
        "items": draft["items"],
        "selected": [0],
        "session_id": "meeting-session",
        "source": {"conversation_id": "conversation-1", "artifact_uri": "office://meeting.docx"},
    }
    queued = approvals.propose(
        category="work_item", title="후속 업무", description="확정", payload=payload, cfg={}
    )
    approved = approvals.approve(
        cast("str", queued["id"]), approved_by="human:reviewer", approved_via="test"
    )
    assert approved["ok"] is True
    groups = work_items.grouped(
        now=datetime(2026, 9, 5, 3, tzinfo=timezone.utc)
    )
    item = cast("list[dict[str, object]]", groups["needs_confirmation"])[0]
    assert item["assignee"] == "민지"
    assert item["due_date"] is None
    assert cast("dict[str, str]", item["source"])["conversation_id"] == "conversation-1"
    assert json.loads(cast("str", approved["result"]))["status"] == "applied"


def test_today_overdue_and_recent_completion_survive_each_write(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setattr(work_items, "_now", lambda: "2026-09-05T03:00:00+00:00")
    overdue = json.loads(work_items.apply_approved({
        "action": "create", "title": "지연 업무", "assignee": "민지", "due_date": "2026-09-04"
    }))["items"][0]
    today = json.loads(work_items.apply_approved({
        "action": "create", "title": "오늘 업무", "assignee": "민지", "due_date": "2026-09-05"
    }))["items"][0]
    _ = overdue
    _ = work_items.apply_approved({"action": "complete", "id": today["id"]})
    groups = work_items.grouped(
        now=datetime(2026, 9, 5, 3, tzinfo=timezone.utc)
    )
    assert [item["title"] for item in groups["overdue"]] == ["지연 업무"]
    assert groups["today"] == []
    assert [item["title"] for item in groups["recently_completed"]] == ["오늘 업무"]

    snapshot = WorkspaceService(
        root=tmp_path / "workspace", session_id="session-1", handlers={}
    ).snapshot()
    panel = next(panel for panel in snapshot.panels if panel.key == "tasks_runs")
    assert any(item["summary"] == "지연 업무" and item["status"] == "지연" for item in panel.items)
