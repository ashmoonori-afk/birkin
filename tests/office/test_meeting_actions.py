from __future__ import annotations

import pytest

from birkin.office.errors import DocumentError
from birkin.office.meeting_actions import review_meeting_actions


def test_meeting_actions_keep_unknowns_evidence_and_confirmation_boundary() -> None:
    notes = "민지는 견적을 확인한다. 출시일은 정하지 않았다."
    result = review_meeting_actions(notes, [
        {"action": "견적 확인", "evidence": "민지는 견적을 확인한다.", "assignee": "민지"},
        {"action": "견적 확인", "evidence": "민지는 견적을 확인한다.", "assignee": "민지"},
        {"action": "출시 준비", "evidence": "출시일은 정하지 않았다.", "suggested_due_date": "2026-09-08"},
    ])
    assert result["confirmation_required"] is True
    assert result["persisted"] is False
    assert len(result["items"]) == 2
    second = result["items"][1]
    assert second["assignee"] is None
    assert second["due_date"] is None
    assert second["suggested_due_date"] == "2026-09-08"


def test_meeting_action_rejects_invented_evidence_and_invalid_date() -> None:
    with pytest.raises(DocumentError, match="exact notes substring"):
        _ = review_meeting_actions("회의 종료", [{"action": "발송", "evidence": "메일 발송"}])
    with pytest.raises(DocumentError, match="ISO date"):
        _ = review_meeting_actions("메일 발송", [{"action": "발송", "evidence": "메일 발송", "due_date": "내일"}])
