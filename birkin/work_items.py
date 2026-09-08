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


def _meeting_items(payload: Mapping[str, object]) -> list[dict[str, object]]:
    draft = payload.get("items")
    if not isinstance(draft, list) or meeting_draft_sha256(draft) != payload.get("draft_sha256"):
        raise ValueError("meeting action draft hash changed")
    selected = payload.get("selected")
    if not isinstance(selected, Sequence) or isinstance(selected, (str, bytes)):
        raise ValueError("selected must be an index list")
    indexes = sorted(set(selected))
    if any(isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= len(draft) for index in indexes):
        raise ValueError("selected meeting action index is invalid")
    items: list[dict[str, object]] = []
    for index in indexes:
        candidate = draft[index]
        if not isinstance(candidate, Mapping):
            raise ValueError("meeting action item is invalid")
        items.append(_new_item({
            "title": candidate.get("action"),
            "assignee": candidate.get("assignee"),
            "due_date": candidate.get("due_date"),
            "evidence": candidate.get("evidence"),
            "session_id": payload.get("session_id"),
            "source": payload.get("source"),
        }))
    return items


def request_review(payload: Mapping[str, object]) -> tuple[str, str]:
    """Validate and describe the exact work-item change before approval."""
    action = payload.get("action")
    if action == "create":
        items = [_new_item(payload)]
        heading = "후속 업무 생성 확인"
    elif action == "confirm_meeting":
        items = _meeting_items(payload)
        if not items:
            raise ValueError("selected meeting actions must not be empty")
        heading = "회의 후속 업무 등록 확인"
    elif action in {"update", "complete"}:
        item = find(payload.get("id"))
        if action == "update":
            if "title" in payload:
                _ = _title(payload["title"])
            if "assignee" in payload:
                _ = _optional_text(payload["assignee"], "assignee")
            if "due_date" in payload:
                _ = _due_date(payload["due_date"])
            if "source" in payload:
                _ = _source(payload["source"])
            item = {**item, **{key: payload[key] for key in ("title", "assignee", "due_date", "source") if key in payload}}
            heading = "후속 업무 수정 확인"
        else:
            heading = "후속 업무 완료 확인"
        items = [item]
    else:
        raise ValueError("unsupported work item action")

    lines = []
    for item in items:
        source = _source(item.get("source"))
        source_text = ", ".join(f"{key}={value}" for key, value in source.items()) or "없음"
        lines.append(
            f"업무: {_title(item.get('title'))} · 담당자: {item.get('assignee') or '미정'}"
            f" · 기한: {item.get('due_date') or '미정'} · 원본: {source_text}"
        )
    return heading, "\n".join(lines)


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
            changed = _meeting_items(payload)
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
        "today": [], "upcoming": [], "overdue": [], "needs_confirmation": [], "recently_completed": []
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
        elif parsed_due is not None:
            groups["upcoming"].append(item)
        if item.get("assignee") is None or parsed_due is None:
            groups["needs_confirmation"].append(item)
    return {"timezone": timezone_name, "date": today.isoformat(), **groups}


def find(item_id: object) -> dict[str, object]:
    """Load one persisted work item by its opaque identifier."""
    with store.file_lock(config.work_items_path()):
        return dict(_find(_read(), item_id))


def source_details(item: Mapping[str, object]) -> dict[str, object]:
    """Resolve a work-item source through its canonical durable authority."""
    source = _source(item.get("source"))
    source_type, target = next(iter(source.items()), ("", ""))
    if source_type == "job_id":
        from .office.coordinator_data import canonical_office_home, job_journal
        from .office.create_journal import CreationJobJournal
        from .office.errors import DocumentError

        creation = False
        try:
            receipt = job_journal(canonical_office_home()).latest(target)
        except DocumentError as job_error:
            try:
                receipt = CreationJobJournal(canonical_office_home()).latest(target)
            except (DocumentError, ValueError):
                raise ValueError("결과 영수증을 찾을 수 없습니다") from job_error
            if not receipt:
                raise ValueError("결과 영수증을 찾을 수 없습니다") from job_error
            creation = True
        if creation:
            from .workspace.approval_receipts import OfficeReceiptProjection

            approval = receipt.get("approval")
            result = receipt.get("result")
            if not isinstance(approval, Mapping) or not isinstance(result, Mapping):
                raise ValueError("결과 영수증 구조가 올바르지 않습니다")
            try:
                projection = OfficeReceiptProjection.from_result(
                    "work-item-source",
                    {"category": "office_create", "payload": approval},
                    json.dumps(result, ensure_ascii=False),
                )
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("결과 영수증 구조가 올바르지 않습니다") from exc
            if projection is None:
                raise ValueError("결과 영수증 구조가 올바르지 않습니다")
            rollback = receipt.get("rollback")
            rollback_summary = (
                "되돌리기 완료"
                if isinstance(rollback, Mapping)
                else " · ".join(filter(None, (
                    "되돌리기 가능",
                    f"만료 {projection.expires_at}",
                    "기존 파일 백업 있음" if projection.backup_exists else "새 파일 삭제로 복원",
                )))
            )
            return {
                "source_type": source_type,
                "target": target,
                "title": "Office 작업 결과 영수증",
                "summary": str(approval.get("outcome") or "Office 문서 생성"),
                "status": str(receipt.get("state") or "상태 미상"),
                "destination": projection.destination,
                "validation": (
                    f"{projection.validation_summary} · "
                    f"{projection.visual_validation_summary}"
                ),
                "failure": "",
                "rollback": rollback_summary,
            }
        state = str(receipt.get("state") or "상태 미상")
        outcome = receipt.get("outcome")
        if not isinstance(outcome, str):
            result = receipt.get("result")
            outcome = str(result.get("outcome") or "") if isinstance(result, Mapping) else ""
        export = receipt.get("export")
        result = receipt.get("result")
        if not isinstance(export, Mapping) and isinstance(result, Mapping):
            export = result.get("export")
        validation = receipt.get("validation")
        failure = receipt.get("failure")
        rollback = receipt.get("rollback")
        destination = str(export.get("path") or export.get("destination") or "") if isinstance(export, Mapping) else ""
        validation_summary = ""
        if isinstance(validation, Mapping):
            validation_value = validation.get("summary") or validation.get("status")
            validation_summary = {
                "pass": "통과", "passed": "통과", "failed": "실패",
            }.get(str(validation_value).lower(), str(validation_value or ""))
            if not validation_summary and validation.get("valid") is True:
                validation_summary = "통과"
        failure_summary = ""
        if isinstance(failure, Mapping):
            failure_summary = str(failure.get("message") or failure.get("reason") or failure.get("code") or "작업 실패")
        rollback_summary = ""
        if isinstance(rollback, Mapping):
            rollback_value = rollback.get("summary") or rollback.get("status")
            rollback_summary = {
                "completed": "완료", "succeeded": "완료", "failed": "실패",
            }.get(str(rollback_value).lower(), str(rollback_value or "되돌리기 기록 있음"))
        return {
            "source_type": source_type,
            "target": target,
            "title": "Office 작업 결과 영수증",
            "summary": outcome or f"작업 상태: {state}",
            "status": state,
            "destination": destination,
            "validation": validation_summary,
            "failure": failure_summary,
            "rollback": rollback_summary,
        }
    if source_type == "goal_slug":
        from . import goals

        session_id = item.get("session_id")
        goal = goals.get_by_slug(
            target,
            session_id=session_id if isinstance(session_id, str) and session_id else None,
        )
        if goal is None:
            raise ValueError("관련 목표를 찾을 수 없습니다")
        return {
            "source_type": source_type,
            "target": target,
            "title": "관련 목표",
            "summary": goal.objective,
            "status": goal.status,
            "session_id": goal.session_id or "",
        }
    if source_type in {"conversation_id", "artifact_uri"}:
        return {"source_type": source_type, "target": target}
    raise ValueError("후속 업무에 연결된 원본이 없습니다")


def projected_rows() -> tuple[dict[str, object], ...]:
    """Project persisted work items for the native tasks panel."""
    groups = grouped()
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    labels = {
        "overdue": "지연", "today": "오늘", "upcoming": "예정",
        "needs_confirmation": "확인 필요", "recently_completed": "최근 완료",
    }
    for group, label in labels.items():
        for item in cast("list[dict[str, object]]", groups[group]):
            item_id = str(item["id"])
            if item_id in seen:
                continue
            seen.add(item_id)
            source = cast("dict[str, str]", item["source"])
            source_type, target = next(iter(source.items()), ("", ""))
            details: dict[str, object] = {}
            if source_type in {"job_id", "goal_slug"}:
                try:
                    resolved = source_details(item)
                    details = {
                        f"source_{key}": str(resolved.get(value) or "")
                        for key, value in {
                            "detail": "summary", "status": "status",
                            "destination": "destination", "validation": "validation",
                            "failure": "failure", "rollback": "rollback",
                        }.items()
                    }
                except ValueError as exc:
                    details = {"source_detail": str(exc), "source_status": "unavailable"}
            rows.append({
                "id": item_id, "kind": "work_item", "summary": item["title"],
                "description": " · ".join(filter(None, [
                    str(item.get("assignee") or "담당자 미정"),
                    str(item.get("due_date") or "기한 미정"),
                ])),
                "status": label, "updated_at": item["updated_at"],
                "assignee": item.get("assignee"), "due_date": item.get("due_date"),
                "session_id": item.get("session_id") or "",
                "source_type": source_type, "target": target, **details,
            })
    return tuple(rows)


__all__ = [
    "apply_approved", "find", "grouped", "projected_rows", "request_review",
    "source_details",
]
