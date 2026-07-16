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
            value: str, enabled: bool = True,
            deliver_chat_id: str | None = None) -> dict[str, Any]:
    job = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "hour": int(hour),
        "minute": int(minute),
        "type": action_type,  # "prompt" | "shell"
        "value": value,
        "enabled": enabled,
        # Telegram chat to notify with the job's output (optional). The
        # scheduler honors the [SILENT] convention before sending.
        "deliver_chat_id": str(deliver_chat_id) if deliver_chat_id else None,
        "created": datetime.now().isoformat(timespec="seconds"),
        "last_run": None,
    }
    # cron.json is mutated by two processes (gateway /remind + scheduler
    # daemon mark_ran) — lock the whole read-modify-write so neither clobbers
    # the other's change (e.g. a mark_ran landing on a pre-delete snapshot).
    with store.file_lock(config.cron_path()):
        jobs = load_jobs()
        jobs.append(job)
        save_jobs(jobs)
    return job


def remove_job(job_id: str) -> bool:
    with store.file_lock(config.cron_path()):
        jobs = load_jobs()
        new = [j for j in jobs if j.get("id") != job_id]
        if len(new) == len(jobs):
            return False
        save_jobs(new)
    return True


def mark_ran(job_id: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with store.file_lock(config.cron_path()):
        jobs = [
            {**j, "last_run": now} if j.get("id") == job_id else j
            for j in load_jobs()
        ]
        save_jobs(jobs)


def claim_if_due(job_id: str, now: datetime | None = None) -> bool:
    """Atomically stamp last_run=today for ``job_id`` IFF it hasn't run today,
    all under the cron lock. Returns True only for the caller that won the
    claim — so two daemons reading the same due job can't both run it (the
    loser sees last_run==today and gets False). The caller runs the job only
    when this returns True."""
    now = now or datetime.now()
    stamp = now.isoformat(timespec="seconds")
    today = date.today().isoformat()
    try:
        with store.file_lock(config.cron_path()):
            jobs = load_jobs()
            job = next((j for j in jobs if j.get("id") == job_id), None)
            if job is None or (job.get("last_run") or "")[:10] == today:
                return False
            job["last_run"] = stamp
            save_jobs(jobs)
            return True
    except store.FileLockTimeout:
        return False


def due_jobs(now: datetime | None = None) -> list[dict[str, Any]]:
    """Jobs enabled, scheduled at/before now today, and not yet run today."""
    now = now or datetime.now()
    # `date.today()` (local real today) intentionally matches mark_ran(), which
    # stamps last_run with datetime.now(); the scheduler always passes a local
    # `now`, so now.date() == today in production.
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
