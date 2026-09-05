"""Deterministic in-app daily briefing over existing work records."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from . import config, cron, store
from .m365_calendar import calendar_view
from .m365_connection import status as connection_status
from .m365_graph import GraphError
from .m365_mail import list_messages
from .work_items import grouped


def generate(job: dict[str, Any], *, now: datetime | None = None) -> dict[str, object]:
    basis = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    occurrence = str(job.get("next_run") or basis.date().isoformat())
    key = hashlib.sha256(f"{job.get('id')}\0{occurrence}".encode()).hexdigest()
    path = config.briefings_dir() / f"{key}.json"
    if path.is_file():
        existing = store._read_json(path, {})
        return {**existing, "created": False} if isinstance(existing, dict) else {"created": False}
    work = grouped(now=basis)
    missing: list[dict[str, str]] = []
    calendar: list[object] = []
    mail: list[object] = []
    connection = connection_status()
    if connection["state"] == "connected":
        try:
            calendar = calendar_view(basis.isoformat(), (basis + timedelta(days=1)).isoformat())["events"]
        except GraphError as exc:
            missing.append({"source": "calendar", "reason": type(exc).__name__})
        try:
            mail = list_messages(limit=20)["messages"]
        except GraphError as exc:
            missing.append({"source": "mail", "reason": type(exc).__name__})
    else:
        missing.append({"source": "microsoft-365", "reason": str(connection["state"])})
    report: dict[str, object] = {
        "id": key,
        "job_id": job.get("id"),
        "data_basis_at": basis.isoformat(timespec="seconds"),
        "calendar": calendar,
        "overdue_work": work["overdue"],
        "today_work": work["today"],
        "pending_approvals": len(store.list_pending()),
        "unread_mail": mail,
        "recent_changes": store.list_runs(limit=10),
        "unreadable_connections": missing,
        "delivery": "in_app_only",
        "created": True,
    }
    store._write_json(path, report)
    return report


def apply_schedule(payload: dict[str, Any], _on_event: object = None) -> str:
    action = payload.get("action")
    if action == "create":
        policy = payload.get("missed_policy", "run")
        if policy not in {"run", "skip"}:
            raise ValueError("missed_policy must be run or skip")
        job = cron.add_job(
            name=str(payload.get("name") or "Daily briefing"),
            action_type="briefing",
            value=json.dumps({"timezone": payload.get("timezone_name", "Asia/Seoul"), "missed_policy": policy}),
            schedule=str(payload.get("schedule") or "09:00"),
        )
        result: object = job
    elif action in {"pause", "resume"}:
        if not cron.set_enabled(str(payload.get("job_id", "")), action == "resume"):
            raise ValueError("briefing job was not found")
        result = {"job_id": payload["job_id"], "enabled": action == "resume"}
    elif action == "skip":
        if not cron.skip_next(str(payload.get("job_id", ""))):
            raise ValueError("briefing job was not found")
        result = {"job_id": payload["job_id"], "skipped": True}
    else:
        raise ValueError("unsupported briefing schedule action")
    return json.dumps({"status": "applied", "result": result}, ensure_ascii=False, sort_keys=True)


def latest(limit: int = 20) -> list[dict[str, object]]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    out = []
    for path in sorted(config.briefings_dir().glob("*.json"), key=lambda item: item.stat().st_mtime_ns, reverse=True):
        record = store._read_json(path, {})
        if isinstance(record, dict):
            out.append(record)
        if len(out) == limit:
            break
    return out


__all__ = ["apply_schedule", "generate", "latest"]
