from __future__ import annotations

import json
from pathlib import Path

import pytest

from birkin.m365_calendar import (
    calendar_view,
    create_local_event,
    execute_approved_event,
    propose_slots,
)


class FakeCalendarGraph:
    def __init__(self, *, conflict: bool = False, etag: str = "etag-1") -> None:
        self.conflict = conflict
        self.etag = etag
        self.calls = []

    def request(self, method, path, body=None, *, headers=None):
        self.calls.append((method, path, body, headers))
        if method == "GET" and path.startswith("/me/calendarView?"):
            return {"value": [{"id": "busy", "showAs": "busy"}]} if self.conflict else {"value": []}
        if method == "GET" and path.startswith("/me/events/"):
            return {"id": "event-1", "@odata.etag": self.etag}
        if method == "POST" and path == "/me/events":
            return {"id": "event-new", "@odata.etag": "etag-new"}
        if method == "PATCH":
            return {"id": "event-1", "@odata.etag": "etag-2"}
        return {}


def test_calendar_view_slots_and_unknown_attendees() -> None:
    graph = FakeCalendarGraph()
    view = calendar_view("2026-09-07T09:00:00+09:00", "2026-09-07T13:00:00+09:00", client=graph)
    slots = propose_slots(
        "2026-09-07T09:00:00+09:00", "2026-09-07T13:00:00+09:00",
        duration_minutes=60, timezone_name="Asia/Seoul",
        busy=[{"start": "2026-09-07T10:00:00+09:00", "end": "2026-09-07T11:00:00+09:00"}],
        attendees=["known@example.com", "unknown@example.com"], attendee_busy_provided=["known@example.com"],
    )
    assert view["occurrences_and_exceptions"] is True
    assert slots["candidates"][0]["start"] == "2026-09-07T09:00:00+09:00"
    assert slots["unknown_attendees"] == ["unknown@example.com"]


def test_event_draft_sends_no_invite_and_rechecks_conflict(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    draft = create_local_event({
        "action": "create", "subject": "검토 회의",
        "start": "2026-09-07T09:00:00+09:00", "end": "2026-09-07T10:00:00+09:00",
        "timezone": "Asia/Seoul", "attendees": ["a@example.com"], "location": "Room 1", "body": "Agenda",
    })
    graph = FakeCalendarGraph()
    receipt = json.loads(execute_approved_event(draft, client=graph))
    assert receipt["status"] == "applied"
    assert [call[0] for call in graph.calls] == ["GET", "POST"]
    assert graph.calls[1][2]["transactionId"] == draft["id"]

    with pytest.raises(ValueError, match="conflict"):
        execute_approved_event(draft, client=FakeCalendarGraph(conflict=True))


def test_event_update_rejects_stale_version_and_uses_if_match(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    draft = create_local_event({
        "action": "update", "event_id": "event-1", "source_etag": "etag-1", "subject": "변경 회의",
        "start": "2026-09-07T09:00:00+09:00", "end": "2026-09-07T10:00:00+09:00",
        "timezone": "Asia/Seoul", "attendees": [],
    })
    stale = FakeCalendarGraph(etag="etag-new")
    with pytest.raises(ValueError, match="changed"):
        execute_approved_event(draft, client=stale)

    current = FakeCalendarGraph()
    _ = execute_approved_event(draft, client=current)
    patch = current.calls[-1]
    assert patch[0] == "PATCH" and patch[3] == {"If-Match": "etag-1"}
