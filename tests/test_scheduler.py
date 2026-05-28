"""Offline tests for the scheduler helpers and job dispatcher."""

from __future__ import annotations

import subprocess
from datetime import datetime

from birkin import cron, scheduler, store


def test_next_nightly_today_vs_tomorrow():
    cfg = {"nightly_hour": 4, "nightly_minute": 0}
    # before today's 04:00 → today
    before = datetime(2026, 5, 28, 1, 30)
    n = scheduler._next_nightly(cfg, before)
    assert n == datetime(2026, 5, 28, 4, 0)
    # after today's 04:00 → tomorrow
    after = datetime(2026, 5, 28, 5, 30)
    n2 = scheduler._next_nightly(cfg, after)
    assert n2 == datetime(2026, 5, 29, 4, 0)


def test_next_nightly_custom_hour():
    cfg = {"nightly_hour": 21, "nightly_minute": 30}
    now = datetime(2026, 5, 28, 21, 31)
    n = scheduler._next_nightly(cfg, now)
    assert n == datetime(2026, 5, 29, 21, 30)


def test_run_job_shell_records_run(monkeypatch):
    captured = {}

    def fake_run(argv, **kw):
        captured["argv"] = argv
        captured["kw"] = kw

        class R:
            stdout = "hello"
            stderr = ""
            returncode = 0
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    job = {"id": "j1", "name": "morning", "type": "shell",
           "value": "echo hi"}
    scheduler._run_job(job)
    runs = store.list_runs()
    assert any(r["kind"] == "cron" for r in runs)
    # argv form (no shell=True) and the command was wrapped via shell_argv
    assert "echo hi" in captured["argv"]


def test_run_job_prompt_skips_without_key(monkeypatch):
    """Prompt-type cron job tries to build a session; without a key it must skip
    cleanly (and record a 'skipped' run) instead of crashing."""
    job = {"id": "j2", "name": "digest", "type": "prompt",
           "value": "summarise yesterday"}
    scheduler._run_job(job)
    runs = store.list_runs()
    assert any(r["kind"] == "cron" and "skipped" in r["summary"].lower()
               for r in runs)


def test_write_status_round_trip():
    cfg = {"nightly_hour": 4, "nightly_minute": 0}
    cron.add_job(name="m", hour=9, minute=0, action_type="prompt", value="x")
    next_n = datetime(2026, 5, 29, 4, 0)
    scheduler._write_status(cfg, next_n, running=True)
    st = store.read_status()
    assert st["daemon"] is True
    assert st["next_nightly"].startswith("2026-05-29")
    assert any(j["name"] == "m" for j in st["cron_jobs"])
