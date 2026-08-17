"""Offline tests for the CLI parser and the inspection commands
(runs / tools / permission / cron). Chat/web/daemon/setup/onboard/gateway are
interactive or long-running and are exercised by their own focused tests."""

from __future__ import annotations

import os
import subprocess
import sysconfig
from pathlib import Path

from birkin import config, cron, store
from birkin.cli import (
    _cmd_chat,
    _cmd_cron,
    _cmd_permission,
    _cmd_runs,
    _cmd_tools,
    build_parser,
)

SUBCOMMANDS = [
    "chat", "skills", "web", "setup", "onboard", "gateway", "tools",
    "model", "daemon", "review", "permission", "cron", "runs",
]


def test_installed_console_script_help():
    script = Path(sysconfig.get_path("scripts")) / (
        "birkin.exe" if sysconfig.get_platform().startswith("win") else "birkin"
    )
    assert script.is_file()

    result = subprocess.run(
        [str(script), "--help"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        encoding="cp1252",
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "chat" in result.stdout
    assert "mcp-serve" in result.stdout


def test_top_level_help_hides_legacy_nightly_alias():
    assert "nightly" not in build_parser().format_help()


def test_installed_console_script_version():
    from birkin import __version__

    script = Path(sysconfig.get_path("scripts")) / (
        "birkin.exe" if sysconfig.get_platform().startswith("win") else "birkin"
    )
    result = subprocess.run(
        [str(script), "--version"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        encoding="cp1252",
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"birkin {__version__}"


def test_help_survives_a_legacy_windows_pipe_encoding():
    """A piped --help on Windows encodes with cp1252; it must not crash."""
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "birkin", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        env=dict(os.environ, PYTHONIOENCODING="cp1252"),
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert "plan -> critique" in result.stdout.decode("utf-8", "replace")


def test_force_utf8_output_pins_both_streams(monkeypatch):
    """cp1252 cannot encode this UI's Korean text; the entry point pins UTF-8."""
    from birkin import cli

    class _Stream:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def reconfigure(self, **kwargs: str) -> None:
            self.calls.append(kwargs)

    out, err = _Stream(), _Stream()
    monkeypatch.setattr(cli.sys, "stdout", out)
    monkeypatch.setattr(cli.sys, "stderr", err)

    cli._force_utf8_output()

    assert out.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert err.calls == out.calls


def test_force_utf8_output_tolerates_a_stream_without_reconfigure(monkeypatch):
    from birkin import cli

    class _Bare:
        pass

    monkeypatch.setattr(cli.sys, "stdout", _Bare())
    monkeypatch.setattr(cli.sys, "stderr", _Bare())

    cli._force_utf8_output()      # a test double must not break the CLI


def test_parser_accepts_every_subcommand():
    p = build_parser()
    for cmd in SUBCOMMANDS:
        ns = p.parse_args([cmd])
        assert getattr(ns, "command", cmd) == cmd
        assert callable(ns.func)


def test_parser_accepts_working_memory_actions():
    parser = build_parser()

    update = parser.parse_args([
        "working-memory", "update", "--session", "session-1",
        "--goal", "Ship it", "--next-action", "Test it",
    ])
    show = parser.parse_args([
        "working-memory", "show", "--session", "session-1", "--json",
    ])
    clear = parser.parse_args([
        "working-memory", "clear", "--session", "session-1",
    ])

    assert update.working_memory_action == "update"
    assert update.next_actions == ["Test it"]
    assert show.working_memory_action == "show"
    assert show.json is True
    assert clear.working_memory_action == "clear"


def test_parser_dry_run_flag_on_chat():
    p = build_parser()
    ns = p.parse_args(["chat", "--dry-run", "-m", "hi"])
    assert ns.dry_run is True
    assert ns.message == "hi"


def test_parser_accepts_positional_dry_run_message():
    p = build_parser()
    ns = p.parse_args(["chat", "--dry-run", "wiring-smoke"])
    assert ns.positional_message == "wiring-smoke"
    assert ns.message is None


def test_chat_dry_run_rejects_two_message_sources(capsys):
    p = build_parser()
    ns = p.parse_args(
        ["chat", "--dry-run", "positional", "-m", "flagged"]
    )
    assert _cmd_chat(ns) == 2
    assert capsys.readouterr().err


def test_chat_rejects_positional_message_without_dry_run(capsys):
    p = build_parser()
    ns = p.parse_args(["chat", "wiring-smoke"])
    assert _cmd_chat(ns) == 2
    assert capsys.readouterr().err


def test_cmd_curate_parses_dry_run_and_reports(capsys):
    from birkin.cli import _cmd_curate
    ns = build_parser().parse_args(["curate", "--dry-run"])
    assert ns.dry_run is True
    ns2 = build_parser().parse_args(["curate"])
    assert ns2.dry_run is False
    assert _cmd_curate(ns) == 0
    assert "checked" in capsys.readouterr().out


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
    assert all(
        group in out
        for group in ("files", "shell", "sessions", "skills", "egress")
    )
    assert "vision_analyze" in out


def test_cmd_tools_panel_includes_opted_in_desktop_tools(capsys):
    # Given
    cfg = config.load_config()
    cfg["desktop_tools"] = True
    config.save_config(cfg)

    # When
    rc = _cmd_tools(_ns(enable=None, disable=None))
    out = capsys.readouterr().out

    # Then
    assert rc == 0
    assert "desktop_windows" in out
    assert "window_screenshot" in out


def test_cmd_tools_panel_restores_bypass_tools_when_enforcement_off(capsys):
    cfg = config.load_config()
    cfg["provider"] = "anthropic"
    cfg["model"] = "claude-sonnet-4-6"
    cfg["egress"]["enforced"] = False
    config.save_config(cfg)

    rc = _cmd_tools(_ns(enable=None, disable=None))
    out = capsys.readouterr().out

    assert rc == 0
    assert "shell" in out
    assert "subagent" in out


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


def test_cmd_cron_remove_reports_busy_lock(capsys, monkeypatch):
    path = config.cron_path()
    job = cron.add_job(
        name="keep",
        hour=9,
        minute=0,
        action_type="prompt",
        value="x",
    )
    before = (path.exists(), path.read_bytes())

    class BusyLock:
        def __enter__(self):
            raise store.FileLockTimeout("busy")

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(store, "file_lock", lambda _path: BusyLock())

    rc = _cmd_cron(_ns(remove=job["id"]))
    captured = capsys.readouterr()

    assert rc == 1
    assert captured.out == "cron store is busy; retry.\n"
    assert captured.err == ""
    assert "Traceback" not in captured.out
    assert (path.exists(), path.read_bytes()) == before
