"""Offline tests for the CLI parser and the inspection commands
(runs / tools / permission / cron). Chat/web/daemon/setup/onboard/gateway are
interactive or long-running and are exercised by their own focused tests."""

from __future__ import annotations

from birkin import config, cron, store
from birkin.cli import (
    _cmd_cron,
    _cmd_permission,
    _cmd_runs,
    _cmd_tools,
    build_parser,
)


SUBCOMMANDS = [
    "chat", "skills", "web", "setup", "onboard", "gateway", "tools",
    "model", "nightly", "daemon", "review", "permission", "cron", "runs",
]


def test_parser_accepts_every_subcommand():
    p = build_parser()
    for cmd in SUBCOMMANDS:
        ns = p.parse_args([cmd])
        assert getattr(ns, "command", cmd) == cmd
        assert callable(ns.func)


def test_parser_dry_run_flag_on_chat():
    p = build_parser()
    ns = p.parse_args(["chat", "--dry-run", "-m", "hi"])
    assert ns.dry_run is True
    assert ns.message == "hi"


def test_cmd_reindex_prints_stats(capsys):
    from birkin.cli import _cmd_reindex
    from birkin.memory import VaultMemory
    m = VaultMemory(config.load_config())
    m.write_note("R1", "alpha", note_type="fact")
    m.write_note("R2", "beta", note_type="project")
    ns = build_parser().parse_args(["reindex"])
    assert _cmd_reindex(ns) == 0
    out = capsys.readouterr().out
    assert "2 notes" in out and "zones" in out and "stale" in out


def _ns(**kw):
    """Build a permissive Namespace for the inspection commands."""
    import argparse
    return argparse.Namespace(**kw)


def test_cmd_runs_lists_recent(capsys):
    store.save_run("chat", "first reply", details={"tools": ["read_file"]},
                   usage=store.estimate_usage("p" * 40))
    rc = _cmd_runs(_ns(limit=10))
    out = capsys.readouterr().out
    assert rc == 0
    assert "chat" in out and "first reply" in out
    assert "read_file" in out                # tools listed


def test_cmd_runs_empty(capsys):
    rc = _cmd_runs(_ns(limit=10))
    assert rc == 0
    assert "No runs recorded yet." in capsys.readouterr().out


def test_cmd_tools_panel(capsys):
    rc = _cmd_tools(_ns(enable=None, disable=None))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Available Tools" in out
    assert "files" in out and "shell" in out and "skills" in out


def test_cmd_tools_toggle_disable_persists(capsys):
    rc = _cmd_tools(_ns(enable=None, disable="run_shell"))
    assert rc == 0
    cfg = config.load_config()
    assert "run_shell" in cfg.get("disabled_tools", [])
    # re-enable
    _cmd_tools(_ns(enable="run_shell", disable=None))
    cfg = config.load_config()
    assert "run_shell" not in cfg.get("disabled_tools", [])


def test_cmd_permission_add_remove_and_access(capsys):
    _cmd_permission(_ns(add="cron", remove=None, access=None))
    cfg = config.load_config()
    assert "cron" in cfg["auto_approve"]

    _cmd_permission(_ns(add=None, remove="cron", access=None))
    cfg = config.load_config()
    assert "cron" not in cfg["auto_approve"]

    _cmd_permission(_ns(add=None, remove=None, access="full"))
    cfg = config.load_config()
    assert cfg["cli_access"] == "full"

    out = capsys.readouterr().out
    assert "CLI-agent access level: full" in out


def test_cmd_cron_lists_and_removes(capsys):
    rc = _cmd_cron(_ns(remove=None))
    out = capsys.readouterr().out
    assert rc == 0 and "No cron jobs" in out

    job = cron.add_job(name="m", hour=9, minute=0, action_type="prompt", value="x")
    rc = _cmd_cron(_ns(remove=None))
    out = capsys.readouterr().out
    assert rc == 0 and job["id"] in out

    rc = _cmd_cron(_ns(remove=job["id"]))
    out = capsys.readouterr().out
    assert rc == 0 and "removed" in out
    assert cron.load_jobs() == []
