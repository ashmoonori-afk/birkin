"""Small approval-backed store for user-confirmed follow-up work."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import config, store
from .office.meeting_actions import meeting_draft_sha256

_SOURCE_KEYS = frozenset({"conversation_id", "artifact_uri", "goal_slug", "job_id"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read() -> list[dict[str, object]]:
    raw = store._read_json(config.work_items_path(), [])
    return [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _write(items: list[dict[str, object]]) -> None:
    store._write_json(config.work_items_path(), items)


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be null or a non-empty string")
    return value.strip()


def _due_date(value: object) -> str | None:
    text = _optional_text(value, "due_date")
    if text is not None:
        _ = date.fromisoformat(text)
    return text


def _title(value: object) -> str:
    title = _optional_text(value, "title")
    if title is None:
        raise ValueError("title is required")
    return title


def _source(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError("source must be an object")
    if unknown := sorted(set(value) - _SOURCE_KEYS):
        raise ValueError(f"source has unsupported keys: {unknown}")
    result: dict[str, str] = {}
    for key, item in value.items():
        text = _optional_text(item, f"source {key}")
        if text is None:
            raise ValueError(f"source {key} must be a non-empty string")
        result[key] = text
    return result


def _new_item(payload: Mapping[str, object]) -> dict[str, object]:
    title = _title(payload.get("title"))
    now = _now()
    return {
        "id": uuid.uuid4().hex,
        "title": title,
        "assignee": _optional_text(payload.get("assignee"), "assignee"),
        "due_date": _due_date(payload.get("due_date")),
        "all_day": True,
        "status": "open",
        "session_id": _optional_text(payload.get("session_id"), "session_id"),
        "source": _source(payload.get("source")),
        "evidence": _optional_text(payload.get("evidence"), "evidence"),
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    }


def _find(items: list[dict[str, object]], item_id: object) -> dict[str, object]:
    if not isinstance(item_id, str):
        raise ValueError("id is required")
    found = next((item for item in items if item.get("id") == item_id), None)
    if found is None:
        raise ValueError("work item was not found")
    return found


def apply_approved(
    payload: dict[str, Any], on_event: Callable[[str, dict[str, object]], None] | None = None
) -> str:
    action = payload.get("action")
    with store.file_lock(config.work_items_path()):
        items = _read()
        changed: list[dict[str, object]] = []
        if action == "create":
            changed = [_new_item(payload)]
            items.extend(changed)
        elif action == "confirm_meeting":
            draft = payload.get("items")
            if not isinstance(draft, list) or meeting_draft_sha256(draft) != payload.get("draft_sha256"):
                raise ValueError("meeting action draft hash changed")
            selected = payload.get("selected")
            if not isinstance(selected, Sequence) or isinstance(selected, (str, bytes)):
                raise ValueError("selected must be an index list")
            indexes = sorted(set(selected))
            if any(isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= len(draft) for index in indexes):
                raise ValueError("selected meeting action index is invalid")
            for index in indexes:
                candidate = draft[index]
                if not isinstance(candidate, Mapping):
                    raise ValueError("meeting action item is invalid")
                changed.append(_new_item({
                    "title": candidate.get("action"),
                    "assignee": candidate.get("assignee"),
                    "due_date": candidate.get("due_date"),
                    "evidence": candidate.get("evidence"),
                    "session_id": payload.get("session_id"),
                    "source": payload.get("source"),
                }))
            items.extend(changed)
        elif action == "update":
            item = _find(items, payload.get("id"))
            for key, parser in (("title", _title), ("assignee", lambda value: _optional_text(value, "assignee")), ("due_date", _due_date)):
                if key in payload:
                    item[key] = parser(payload[key])
            if "source" in payload:
                item["source"] = _source(payload["source"])
            item["updated_at"] = _now()
            changed = [item]
        elif action == "complete":
            item = _find(items, payload.get("id"))
            item["status"] = "done"
            item["updated_at"] = item["completed_at"] = _now()
            changed = [item]
        else:
            raise ValueError("unsupported work item action")
        _write(items)
    if on_event is not None:
        for item in changed:
            source = cast("dict[str, str]", item["source"])
            on_event("task.updated", {
                "task_id": item["id"],
                "summary": item["title"],
                "status": item["status"],
                "session_id": item["session_id"] or "",
                "target": next(iter(source.values()), ""),
            })
    return json.dumps({"status": "applied", "items": changed}, ensure_ascii=False, sort_keys=True)


def grouped(*, timezone_name: str = "Asia/Seoul", now: datetime | None = None) -> dict[str, object]:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("unknown timezone") from exc
    current = (now or datetime.now(timezone.utc)).astimezone(zone)
    today = current.date()
    groups: dict[str, list[dict[str, object]]] = {
        "today": [], "overdue": [], "needs_confirmation": [], "recently_completed": []
    }
    with store.file_lock(config.work_items_path()):
        items = _read()
    for item in items:
        if item.get("status") == "done":
            completed = item.get("completed_at")
            if isinstance(completed, str) and datetime.fromisoformat(completed).astimezone(zone) >= current - timedelta(days=7):
                groups["recently_completed"].append(item)
            continue
        due = item.get("due_date")
        parsed_due = date.fromisoformat(due) if isinstance(due, str) else None
        if parsed_due is not None and parsed_due < today:
            groups["overdue"].append(item)
        elif parsed_due == today:
            groups["today"].append(item)
        if item.get("assignee") is None or parsed_due is None:
            groups["needs_confirmation"].append(item)
    return {"timezone": timezone_name, "date": today.isoformat(), **groups}


__all__ = ["apply_approved", "grouped"]
