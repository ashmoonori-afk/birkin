"""Offline tests for the scheduler helpers and job dispatcher."""

from __future__ import annotations

import subprocess
from datetime import datetime

from birkin import config, cron, monitor, scheduler, store


def test_default_morpheus_proposal_runs_at_seven():
    assert config.DEFAULT_CONFIG["morpheus_hour"] == 7

    before = datetime(2026, 5, 28, 6, 30)
    assert scheduler._next_morpheus({}, before) == datetime(2026, 5, 28, 7, 0)

    after = datetime(2026, 5, 28, 7, 0)
    assert scheduler._next_morpheus({}, after) == datetime(2026, 5, 29, 7, 0)


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


def test_run_job_monitor_unchanged_is_silent_without_prompt(monkeypatch):
    asked = []
    saved = []
    monkeypatch.setattr(
        monitor, "check",
        lambda job: monitor.MonitorResult(False, None, "", "same"),
    )
    monkeypatch.setattr(
        scheduler.store, "save_run",
        lambda *args, **kwargs: saved.append((args, kwargs)),
    )

    class Session:
        def ask(self, *args, **kwargs):
            asked.append((args, kwargs))

    import birkin.runtime as runtime
    monkeypatch.setattr(runtime, "build_session", lambda: Session())

    scheduler._run_job({
        "id": "m1", "name": "watch", "type": "monitor",
        "value": "report changes", "monitor_url": "https://example.test",
    })

    assert asked == []
    assert saved and "[SILENT]" in saved[0][0][1]
    assert saved[0][1]["usage"] == {"tokens": 0}


def test_run_job_monitor_changed_invokes_prompt_with_context(monkeypatch):
    asked = []
    monkeypatch.setattr(
        monitor, "check",
        lambda job: monitor.MonitorResult(
            True, None, "Previous SHA-256: old\nCurrent SHA-256: new",
            "changed body",
        ),
    )

    class Session:
        def ask(self, prompt, **kwargs):
            asked.append((prompt, kwargs))
            return "change reported"

    import birkin.runtime as runtime
    monkeypatch.setattr(runtime, "build_session", lambda: Session())
    monkeypatch.setattr(scheduler, "_deliver", lambda job, text: "none")

    scheduler._run_job({
        "id": "m2", "name": "watch", "type": "monitor",
        "value": "report changes", "monitor_script": "echo changed",
    })

    assert len(asked) == 1
    prompt, kwargs = asked[0]
    assert prompt.startswith("report changes")
    assert "Monitor change context" in prompt
    assert "Previous SHA-256: old" in prompt
    assert "changed body" in prompt
    assert kwargs == {"record_turn": False}


def test_run_job_prompt_skips_without_key(monkeypatch):
    """Prompt-type cron job tries to build a session; without a key it must skip
    cleanly (and record a 'skipped' run) instead of crashing."""
    cfg = config.load_config()
    cfg["provider"] = "anthropic"
    cfg["model"] = "claude-sonnet-4-6"
    config.save_config(cfg)

    job = {"id": "j2", "name": "digest", "type": "prompt",
           "value": "summarise yesterday"}
    scheduler._run_job(job)
    runs = store.list_runs()
    assert any(r["kind"] == "cron" and "skipped" in r["summary"].lower()
               for r in runs)


# ---------------- [SILENT] delivery convention -----------------------------

def test_is_silent_detects_markers():
    assert scheduler._is_silent("[SILENT] nothing new today")
    assert scheduler._is_silent("  NO_REPLY")
    assert not scheduler._is_silent("3 new issues found")
    assert not scheduler._is_silent("")


def test_deliver_none_without_target():
    assert scheduler._deliver({"name": "j"}, "hello") == "none"


def test_deliver_skips_silent_output_before_any_network(monkeypatch):
    sent: list = []
    monkeypatch.setattr(scheduler, "_send_telegram",
                        lambda *a: sent.append(a))
    out = scheduler._deliver({"name": "watch", "deliver_chat_id": "42"},
                             "[SILENT] no changes on the site")
    assert out == "skipped-silent" and sent == []


def test_deliver_sends_real_output(monkeypatch):
    sent: list = []
    monkeypatch.setattr(scheduler, "_send_telegram",
                        lambda token, chat, text: sent.append((chat, text)))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tkn")
    out = scheduler._deliver({"name": "watch", "deliver_chat_id": "42"},
                             "3 new issues found")
    assert out == "sent"
    assert sent and sent[0][0] == "42" and "3 new issues" in sent[0][1]


def test_deliver_reports_missing_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    out = scheduler._deliver({"name": "w", "deliver_chat_id": "42"}, "news")
    assert out.startswith("error: no telegram token")


def test_deliver_refuses_chat_outside_allowlist(monkeypatch):
    """Outbound delivery honors the inbound allowlist — a job payload can't
    exfiltrate run output to a stranger's chat."""
    from birkin import config
    cfg = config.load_config()
    cfg["channels"] = {"telegram": {"allowed_chat_ids": ["1"]}}
    config.save_config(cfg)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tkn")
    sent: list = []
    monkeypatch.setattr(scheduler, "_send_telegram",
                        lambda *a: sent.append(a))
    out = scheduler._deliver({"name": "w", "deliver_chat_id": "42"}, "news")
    assert out.startswith("error: chat_id not in") and sent == []
    ok = scheduler._deliver({"name": "w", "deliver_chat_id": "1"}, "news")
    assert ok == "sent" and sent


def test_deliver_error_status_never_leaks_the_token(monkeypatch):
    """The delivery status string is persisted into run records — a failed
    send must not embed the bot token there."""
    import urllib.error

    def boom(token, chat, text):
        raise urllib.error.HTTPError(
            f"https://api.telegram.org/bot{token}/sendMessage",
            401, "Unauthorized", None, None)

    monkeypatch.setattr(scheduler, "_send_telegram", boom)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "sekret-tkn")
    out = scheduler._deliver({"name": "w", "deliver_chat_id": "42"}, "news")
    assert out.startswith("error:") and "sekret-tkn" not in out


def test_is_silent_marker_must_lead_the_output():
    """A shell job that merely PRINTS the marker mid-output (grepped logs)
    must still deliver its findings."""
    assert not scheduler._is_silent(
        "Found 3 lines: ERROR foo, [SILENT] mode enabled in config, WARN bar")


def test_run_job_shell_records_delivery_status(monkeypatch):
    def fake_run(argv, **kw):
        class R:
            stdout = "[SILENT] all quiet"
            stderr = ""
            returncode = 0
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    scheduler._run_job({"id": "j9", "name": "quiet", "type": "shell",
                        "value": "check", "deliver_chat_id": "7"})
    runs = store.list_runs()
    rec = next(r for r in runs if r["kind"] == "cron"
               and "quiet" in r["summary"])
    assert rec["details"]["delivery"] == "skipped-silent"


def test_write_status_round_trip():
    cfg = {"nightly_hour": 4, "nightly_minute": 0}
    cron.add_job(name="m", hour=9, minute=0, action_type="prompt", value="x")
    next_n = datetime(2026, 5, 29, 4, 0)
    scheduler._write_status(cfg, next_n, running=True)
    st = store.read_status()
    assert st["daemon"] is True
    assert st["next_nightly"].startswith("2026-05-29")
    assert any(j["name"] == "m" for j in st["cron_jobs"])


def test_windows_schedule_pins_configured_workspace(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace root"
    workspace.mkdir()
    captured = {}

    monkeypatch.setattr(
        scheduler.config,
        "load_config",
        lambda: {"workspace_roots": [str(workspace)]},
    )
    monkeypatch.setattr(scheduler.sys, "platform", "win32")
    monkeypatch.setattr(
        scheduler.sys,
        "executable",
        r"C:\Python\python.exe",
    )
    monkeypatch.setenv("USERNAME", "tester")

    class Result:
        returncode = 0
        stdout = "SUCCESS"
        stderr = ""

    def fake_run(args, **kwargs):
        captured["args"] = args
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert scheduler.install_os_schedule() == 0
    args = captured["args"]
    command = args[args.index("/TR") + 1]
    assert f'cd /d ""{workspace}""' in command
    assert r'""C:\Python\python.exe"" -m birkin daemon' in command
