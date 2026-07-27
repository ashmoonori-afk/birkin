"""Two silent no-ops: an OS task that skipped cron, and a typo'd allowlist.

1. `birkin daemon --install` is documented as installing "Morpheus + cron
   scheduler", but install_os_schedule registered `-m birkin morpheus` — a
   one-shot that does NOT poll cron. Only run_daemon() drains cron.due_jobs().
   Measured consequence on the author's machine: two cron jobs approved
   2026-06-02, both enabled, both last_run=None eight weeks later, zero runs
   of kind "cron" across 105 run records, and no status.json heartbeat ever
   written. /remind writes through cron.add_job(), so it never fired either —
   birkin said "scheduled" and nothing was.

2. approvals.is_auto() does exact membership on the category string. The
   category is "skill" (singular), but the docs said "skills", so a config
   carrying the plural silently allowlists nothing — it looks configured and
   behaves as if it were not. birkin's own DEFAULT_CONFIG was corrected long
   ago; the docstring was not, and installs predating the fix still carry it.
"""

from __future__ import annotations

import types

import pytest

from birkin import approvals, scheduler, security


# -- 1. the installed task must be the thing that runs cron ----------------

def _captured_schtasks(monkeypatch, tmp_path):
    seen: dict = {}

    def fake_run(args, **kw):
        seen["args"] = args
        return types.SimpleNamespace(stdout="OK", stderr="", returncode=0)

    monkeypatch.setattr(scheduler.subprocess, "run", fake_run)
    monkeypatch.setattr(scheduler.sys, "platform", "win32")
    monkeypatch.setattr(scheduler.config, "load_config",
                        lambda: {"morpheus_hour": 4, "morpheus_minute": 0,
                                 "workspace_roots": [str(tmp_path)]})
    scheduler.install_os_schedule()
    return seen["args"]


def test_windows_task_runs_the_daemon_not_a_one_shot_morpheus(
        monkeypatch, tmp_path):
    args = _captured_schtasks(monkeypatch, tmp_path)
    cmd = " ".join(args)
    assert "-m birkin daemon" in cmd, (
        "the installed task still runs one-shot morpheus, which never polls cron")
    assert "-m birkin morpheus" not in cmd


def test_windows_task_is_persistent_not_daily(monkeypatch, tmp_path):
    """A daily one-shot cannot host a 30s poll loop; the daemon must survive."""
    args = _captured_schtasks(monkeypatch, tmp_path)
    assert args[args.index("/SC") + 1] == "ONLOGON"
    # /ST is meaningless for ONLOGON and schtasks rejects the combination.
    assert "/ST" not in args
    # Same name as before, so re-running replaces the old daily task (/F).
    assert args[args.index("/TN") + 1] == "birkin-nightly"
    assert "/F" in args


def test_windows_task_is_scoped_to_this_user_so_it_needs_no_elevation(
        monkeypatch, tmp_path):
    """An ONLOGON task with no /RU triggers on ANY user's logon, which only an
    administrator may register — schtasks then fails with a bare
    "Access is denied" that names nothing. Scoping it to the current account
    (/RU) and to sessions where that account is actually logged on (/IT) keeps
    it installable by a plain user and needs no stored password."""
    monkeypatch.setenv("USERNAME", "testuser")
    args = _captured_schtasks(monkeypatch, tmp_path)
    assert args[args.index("/RU") + 1] == "testuser"
    assert "/IT" in args
    assert "/RP" not in args, "must not need a stored password"


def test_denied_registration_falls_back_to_startup(monkeypatch, tmp_path, capsys):
    """Measured on Windows 11 as a plain user: DAILY succeeds, ONLOGON is
    refused with AND without /RU — the logon trigger is the privileged part.
    So "Access is denied" is the NORMAL path here, not an edge case, and it
    must land somewhere that works rather than telling the user to open an
    elevated shell for a personal background process."""
    appdata = tmp_path / "AppData" / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    deleted: list = []

    def fake_run(args, **kw):
        if args[:2] == ["schtasks", "/Delete"]:
            deleted.append(args)
            return types.SimpleNamespace(stdout="", stderr="", returncode=0)
        return types.SimpleNamespace(stdout="", stderr="ERROR: Access is denied.",
                                     returncode=1)

    monkeypatch.setattr(scheduler.subprocess, "run", fake_run)
    monkeypatch.setattr(scheduler.sys, "platform", "win32")
    monkeypatch.setattr(scheduler.config, "load_config",
                        lambda: {"workspace_roots": [str(tmp_path)]})

    rc = scheduler.install_os_schedule()
    out = capsys.readouterr().out
    assert rc == 0, "a denied schtasks must not leave the user with nothing"
    assert "denied" in out                    # the real error still shown
    cmd_file = (appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
                / "Startup" / "birkin-daemon.cmd")
    assert cmd_file.is_file()
    body = cmd_file.read_text(encoding="utf-8")
    assert "-m birkin daemon" in body
    assert str(tmp_path) in body              # runs in the workspace root
    assert str(cmd_file) in out               # user is told exactly what to delete


def test_startup_fallback_retires_the_old_morpheus_task(monkeypatch, tmp_path):
    """Leaving the old birkin-nightly task next to the daemon runs Morpheus
    twice a night — duplicated model spend, not a cosmetic issue."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    calls: list = []

    def fake_run(args, **kw):
        calls.append(args)
        rc = 0 if args[:2] == ["schtasks", "/Delete"] else 1
        return types.SimpleNamespace(stdout="", stderr="denied", returncode=rc)

    monkeypatch.setattr(scheduler.subprocess, "run", fake_run)
    monkeypatch.setattr(scheduler.sys, "platform", "win32")
    monkeypatch.setattr(scheduler.config, "load_config", lambda: {})
    scheduler.install_os_schedule()
    assert any(a[:2] == ["schtasks", "/Delete"] and "birkin-nightly" in a
               for a in calls)


def test_posix_entry_runs_the_daemon_at_boot(monkeypatch, tmp_path):
    written: dict = {}

    def fake_run(args, **kw):
        if args[:2] == ["crontab", "-l"]:
            return types.SimpleNamespace(stdout="", stderr="", returncode=0)
        written["input"] = kw.get("input", "")
        return types.SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(scheduler.subprocess, "run", fake_run)
    monkeypatch.setattr(scheduler.sys, "platform", "linux")
    monkeypatch.setattr(scheduler.config, "load_config",
                        lambda: {"morpheus_hour": 4, "morpheus_minute": 0})
    scheduler.install_os_schedule()
    line = written["input"]
    assert "birkin daemon" in line
    assert "@reboot" in line
    assert "birkin-nightly" in line          # the marker install checks for


def test_only_the_daemon_drains_cron():
    """Pins WHY the task must be the daemon. If cron polling ever moves out of
    run_daemon, this fails and the reasoning above needs revisiting."""
    import inspect
    src = inspect.getsource(scheduler.run_daemon)
    assert "due_jobs" in src
    assert "morpheus" in src                 # the daemon covers both duties


# -- 2. an auto_approve entry that matches nothing is worse than none -------

def test_unknown_auto_approve_category_is_flagged():
    warnings = security.gateway_warnings(
        {"provider": "codex-cli", "auto_approve": ["memory", "skills"]})
    joined = " ".join(warnings)
    assert "skills" in joined, (
        'a plural "skills" silently allowlists nothing and must be surfaced')
    assert "skill" in joined


def test_known_categories_do_not_warn():
    warnings = security.gateway_warnings(
        {"provider": "codex-cli", "auto_approve": ["memory", "skill"]})
    assert not any("auto_approve" in w for w in warnings)


def test_empty_auto_approve_does_not_warn():
    warnings = security.gateway_warnings(
        {"provider": "codex-cli", "auto_approve": []})
    assert not any("auto_approve" in w for w in warnings)


def test_the_categories_named_in_docs_are_the_ones_is_auto_accepts():
    """The typo came from the module docstring disagreeing with the code."""
    doc = approvals.__doc__ or ""
    assert "default ``memory``, ``skill``" in doc, (
        "the docstring still names the plural as the default")
    for category in ("skill", "cron", "shell"):
        assert approvals.is_auto(category, {"auto_approve": [category]}) is True
    assert approvals.is_auto("skill", {"auto_approve": ["skills"]}) is False


# -- 3. a second daemon doubles the nightly bill ---------------------------

def test_a_second_daemon_refuses_to_start(monkeypatch, capsys):
    """cron.claim_if_due protects the job queue, but the Morpheus trigger is a
    per-process time comparison with no claim, so two daemons would run the
    nightly routine twice — duplicated model spend, not a cosmetic race.
    Nothing guarded that before; the Startup entry firing at logon while a
    hand-started daemon is already up reaches it in one step. Verified live:
    a second `birkin daemon` now exits instead of starting.

    Do NOT try to detect this by counting processes. On Windows a venv's
    Scripts/python.exe is a launcher stub that runs the real interpreter as a
    child, so ONE daemon appears as two python.exe entries with identical
    command lines — a shape mistaken for a duplicate while writing this."""
    monkeypatch.setattr(scheduler.store, "read_status",
                        lambda: {"daemon": True, "heartbeat": "now"})
    monkeypatch.setattr(scheduler.store, "is_status_stale", lambda s, **k: False)
    assert scheduler.already_running() is True
    assert scheduler.run_daemon() == 0
    assert "이미 실행 중" in capsys.readouterr().out


def test_a_crashed_daemon_does_not_wedge_the_next_one_shut(monkeypatch):
    """SIGKILL leaves daemon=true on disk; a stale heartbeat must read as
    stopped or birkin can never start again without manual cleanup."""
    monkeypatch.setattr(scheduler.store, "read_status",
                        lambda: {"daemon": True, "heartbeat": "2020-01-01T00:00:00+00:00"})
    monkeypatch.setattr(scheduler.store, "is_status_stale", lambda s, **k: True)
    assert scheduler.already_running() is False


def test_no_status_file_means_free_to_start(monkeypatch):
    monkeypatch.setattr(scheduler.store, "read_status", lambda: {"daemon": False})
    assert scheduler.already_running() is False
