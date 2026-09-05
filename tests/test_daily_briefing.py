from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from birkin import cron
from birkin.daily_briefing import apply_schedule, generate, latest


def test_briefing_is_idempotent_and_marks_unreadable_connection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    job = {"id": "briefing-1", "next_run": "2026-09-05T09:00:00", "name": "Morning"}
    now = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)

    first = generate(job, now=now)
    second = generate(job, now=now)

    assert first["created"] is True and second["created"] is False
    assert first["data_basis_at"] == "2026-09-05T00:00:00+00:00"
    assert first["unreadable_connections"][0]["source"] == "microsoft-365"
    assert first["delivery"] == "in_app_only" and len(latest()) == 1


def test_briefing_schedule_supports_pause_resume_and_skip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    created = apply_schedule({"action": "create", "name": "Morning", "schedule": "09:00", "missed_policy": "skip"})
    job = cron.load_jobs()[0]
    assert '"status": "applied"' in created and job["type"] == "briefing"

    _ = apply_schedule({"action": "pause", "job_id": job["id"]})
    assert cron.load_jobs()[0]["enabled"] is False
    _ = apply_schedule({"action": "resume", "job_id": job["id"]})
    assert cron.load_jobs()[0]["enabled"] is True
    before = cron.load_jobs()[0]["next_run"]
    _ = apply_schedule({"action": "skip", "job_id": job["id"]})
    assert cron.load_jobs()[0]["next_run"] != before
