"""Calendar view, bounded slot proposals, and approval-bound events."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import config, store
from .m365_graph import GraphClient, graph_client
from .office.artifact_serialization import canonical_json


def _instant(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO date-time with an offset")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def calendar_view(start: object, end: object, *, client: GraphClient | None = None) -> dict[str, object]:
    first, last = _instant(start, "start"), _instant(end, "end")
    if last <= first or last - first > timedelta(days=31):
        raise ValueError("calendar range must be positive and at most 31 days")
    query = urlencode({"startDateTime": first.isoformat(), "endDateTime": last.isoformat(), "$top": 500})
    result = (client or graph_client()).request("GET", f"/me/calendarView?{query}")
    values = result.get("value", [])
    return {"events": values if isinstance(values, list) else [], "range": {"start": first.isoformat(), "end": last.isoformat()}, "occurrences_and_exceptions": True}


def propose_slots(
    start: object,
    end: object,
    *,
    duration_minutes: object,
    timezone_name: object,
    busy: object,
    attendees: object,
    attendee_busy_provided: object = (),
    limit: object = 5,
) -> dict[str, object]:
    first, last = _instant(start, "start"), _instant(end, "end")
    if isinstance(duration_minutes, bool) or not isinstance(duration_minutes, int) or not 15 <= duration_minutes <= 480:
        raise ValueError("duration_minutes must be between 15 and 480")
    if not isinstance(timezone_name, str):
        raise ValueError("timezone_name is required")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("unknown timezone") from exc
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    if isinstance(busy, (str, bytes)) or not isinstance(busy, Sequence):
        raise ValueError("busy must be an array")
    intervals: list[tuple[datetime, datetime]] = []
    for item in busy:
        if not isinstance(item, Mapping):
            raise ValueError("busy interval must be an object")
        intervals.append((_instant(item.get("start"), "busy start"), _instant(item.get("end"), "busy end")))
    attendee_list = [str(item) for item in attendees] if isinstance(attendees, Sequence) and not isinstance(attendees, (str, bytes)) else []
    provided = {str(item) for item in attendee_busy_provided} if isinstance(attendee_busy_provided, Sequence) and not isinstance(attendee_busy_provided, (str, bytes)) else set()
    slots = []
    cursor = first.astimezone(zone).replace(second=0, microsecond=0)
    cursor += timedelta(minutes=(-cursor.minute) % 30)
    duration = timedelta(minutes=duration_minutes)
    while cursor + duration <= last.astimezone(zone) and len(slots) < limit:
        finish = cursor + duration
        if cursor.weekday() < 5 and cursor.hour >= 9 and (finish.hour < 18 or (finish.hour == 18 and finish.minute == 0)):
            if all(finish <= occupied_start or cursor >= occupied_end for occupied_start, occupied_end in intervals):
                slots.append({"start": cursor.isoformat(), "end": finish.isoformat(), "timezone": timezone_name})
        cursor += timedelta(minutes=30)
    return {
        "candidates": slots,
        "availability_scope": ["self", *sorted(provided)],
        "unknown_attendees": sorted(set(attendee_list) - provided),
    }


def create_local_event(payload: Mapping[str, object]) -> dict[str, object]:
    action = payload.get("action")
    if action not in {"create", "update"}:
        raise ValueError("event action must be create or update")
    start, end = _instant(payload.get("start"), "start"), _instant(payload.get("end"), "end")
    if end <= start:
        raise ValueError("event end must be after start")
    attendees = payload.get("attendees", [])
    if isinstance(attendees, (str, bytes)) or not isinstance(attendees, Sequence):
        raise ValueError("attendees must be an array")
    if action == "update" and (not payload.get("event_id") or not payload.get("source_etag")):
        raise ValueError("event update requires event_id and source_etag")
    draft: dict[str, object] = {
        "id": uuid.uuid4().hex,
        "action": action,
        "event_id": payload.get("event_id"),
        "source_etag": payload.get("source_etag"),
        "subject": str(payload.get("subject", "")).strip(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "timezone": str(payload.get("timezone", "UTC")),
        "is_all_day": bool(payload.get("is_all_day", False)),
        "attendees": [str(item) for item in attendees],
        "location": str(payload.get("location", "")),
        "body": str(payload.get("body", "")),
    }
    if not draft["subject"]:
        raise ValueError("event subject is required")
    draft["content_sha256"] = hashlib.sha256(canonical_json(draft).encode()).hexdigest()
    with store.file_lock(config.calendar_drafts_path()):
        raw = store._read_json(config.calendar_drafts_path(), {})
        drafts = dict(raw) if isinstance(raw, dict) else {}
        drafts[str(draft["id"])] = draft
        store._write_json(config.calendar_drafts_path(), drafts)
    return draft


def get_local_event(draft_id: object, digest: object) -> dict[str, object]:
    raw = store._read_json(config.calendar_drafts_path(), {})
    draft = raw.get(draft_id) if isinstance(raw, dict) and isinstance(draft_id, str) else None
    if not isinstance(draft, dict) or draft.get("content_sha256") != digest:
        raise ValueError("calendar draft is missing or changed; create a new review")
    copy = dict(draft)
    expected = copy.pop("content_sha256")
    if hashlib.sha256(canonical_json(copy).encode()).hexdigest() != expected:
        raise ValueError("calendar draft changed; create a new review")
    return dict(draft)


def _graph_event(draft: Mapping[str, object]) -> dict[str, object]:
    start = _instant(draft["start"], "start").astimezone(timezone.utc).replace(tzinfo=None).isoformat()
    end = _instant(draft["end"], "end").astimezone(timezone.utc).replace(tzinfo=None).isoformat()
    return {
        "subject": draft["subject"],
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
        "isAllDay": draft["is_all_day"],
        "attendees": [{"emailAddress": {"address": item}, "type": "required"} for item in draft["attendees"]],
        "location": {"displayName": draft["location"]},
        "body": {"contentType": "Text", "content": draft["body"]},
    }


def execute_approved_event(payload: dict[str, Any], client: GraphClient | None = None) -> str:
    draft = get_local_event(payload.get("draft_id", payload.get("id")), payload.get("content_sha256"))
    graph = client or graph_client()
    view = calendar_view(draft["start"], draft["end"], client=graph)
    conflicts = [event for event in view["events"] if isinstance(event, dict) and event.get("id") != draft.get("event_id") and event.get("showAs") not in {"free", "workingElsewhere"}]
    if conflicts:
        raise ValueError("calendar conflict found during final recheck")
    body = _graph_event(draft)
    if draft["action"] == "create":
        body["transactionId"] = draft["id"]
        result = graph.request("POST", "/me/events", body)
    else:
        event_id = quote(str(draft["event_id"]), safe="")
        latest = graph.request("GET", f"/me/events/{event_id}?$select=id,@odata.etag")
        if latest.get("@odata.etag") != draft["source_etag"]:
            raise ValueError("calendar event changed; create a new review")
        result = graph.request("PATCH", f"/me/events/{event_id}", body, headers={"If-Match": str(draft["source_etag"])})
    return json.dumps({"status": "applied", "event": result, "draft_sha256": draft["content_sha256"]}, ensure_ascii=False, sort_keys=True)


__all__ = ["calendar_view", "create_local_event", "execute_approved_event", "get_local_event", "propose_slots"]
