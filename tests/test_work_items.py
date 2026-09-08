from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import cast

import pytest

from birkin import approvals, goals, work_items
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
    title, description = work_items.request_review(payload)
    assert title == "회의 후속 업무 등록 확인"
    assert description == (
        "업무: 견적 확인 · 담당자: 민지 · 기한: 미정"
        " · 원본: conversation_id=conversation-1, artifact_uri=office://meeting.docx"
    )
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


def test_goal_source_is_resolved_from_persisted_authority_after_restart(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    goal = goals.set_goal("분기 보고서 제출", session_id="session-1")
    created = json.loads(work_items.apply_approved({
        "action": "create",
        "title": "보고서 후속 확인",
        "session_id": "session-1",
        "source": {"goal_slug": goal.slug},
    }))["items"][0]

    reloaded = work_items.find(created["id"])
    assert work_items.source_details(reloaded) == {
        "source_type": "goal_slug",
        "target": goal.slug,
        "title": "관련 목표",
        "summary": "분기 보고서 제출",
        "status": "active",
        "session_id": "session-1",
    }


def test_source_resolution_rejects_traversal_and_missing_references(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    sources = ({"goal_slug": "../secret"}, {"job_id": "../secret"}, {"job_id": "missing"})
    for source in sources:
        item = json.loads(work_items.apply_approved({
            "action": "create", "title": "잘못된 참조", "source": source,
        }))["items"][0]
        with pytest.raises(ValueError, match="찾을 수 없습니다|invalid"):
            work_items.source_details(item)
