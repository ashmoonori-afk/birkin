"""Lightweight daily cron jobs (portable, file-based).

A job runs once per day at ``hour:minute``. Its action is either a ``prompt``
(handed to a one-off agent) or a ``shell`` command. Jobs are stored in
``~/.birkin/cron.json``. The :mod:`scheduler` fires due jobs; OS-native
registration is optional (see :mod:`scheduler`).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from . import config, store


def load_jobs() -> list[dict[str, Any]]:
    return store._read_json(config.cron_path(), [])


def save_jobs(jobs: list[dict[str, Any]]) -> None:
    store._write_json(config.cron_path(), jobs)


def add_job(*, name: str, hour: int, minute: int, action_type: str,
            value: str, enabled: bool = True) -> dict[str, Any]:
    job = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "hour": int(hour),
        "minute": int(minute),
        "type": action_type,  # "prompt" | "shell"
        "value": value,
        "enabled": enabled,
        "created": datetime.now().isoformat(timespec="seconds"),
        "last_run": None,
    }
    jobs = load_jobs()
    jobs.append(job)
    save_jobs(jobs)
    return job


def remove_job(job_id: str) -> bool:
    jobs = load_jobs()
    new = [j for j in jobs if j.get("id") != job_id]
    if len(new) == len(jobs):
        return False
    save_jobs(new)
    return True


def mark_ran(job_id: str) -> None:
    jobs = load_jobs()
    for j in jobs:
        if j.get("id") == job_id:
            j["last_run"] = datetime.now().isoformat(timespec="seconds")
    save_jobs(jobs)


def due_jobs(now: datetime | None = None) -> list[dict[str, Any]]:
    """Jobs enabled, scheduled at/before now today, and not yet run today."""
    now = now or datetime.now()
    today = date.today().isoformat()
    out = []
    for j in load_jobs():
        if not j.get("enabled", True):
            continue
        last = (j.get("last_run") or "")[:10]
        if last == today:
            continue
        if (now.hour, now.minute) >= (int(j.get("hour", 0)), int(j.get("minute", 0))):
            out.append(j)
    return out
