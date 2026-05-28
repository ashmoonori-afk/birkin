"""More CLI handler coverage — non-interactive paths that monkeypatch the
side-effectful operations (web/gateway/daemon/nightly/setup)."""

from __future__ import annotations

import argparse
from pathlib import Path

from birkin import cli as cli_mod


def _ns(**kw) -> argparse.Namespace:
    return argparse.Namespace(**kw)


# ---------------- _dry_run (chat --dry-run) ----------------

def test_dry_run_prints_packet_without_calling_llm(capsys):
    rc = cli_mod._dry_run(_ns(message="find arxiv papers on transformers"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry run" in out.lower()
    assert "system prompt" in out.lower()
    assert "No request was sent" in out


def test_dry_run_blank_message_is_noop(capsys, monkeypatch):
    # empty stdin → input() returns "" → return 0
    monkeypatch.setattr("builtins.input", lambda *_: "")
    rc = cli_mod._dry_run(_ns(message=""))
    assert rc == 0


# ---------------- _cmd_skills (list / show / sync) ----------------

def test_cmd_skills_list(capsys):
    rc = cli_mod._cmd_skills(_ns(name=None, source=None, limit=None, force=False))
    out = capsys.readouterr().out
    assert rc == 0 and "web-research" in out


def test_cmd_skills_show_one(capsys):
    rc = cli_mod._cmd_skills(_ns(name="web-research", source=None, limit=None, force=False))
    out = capsys.readouterr().out
    assert rc == 0 and "Web Research" in out


def test_cmd_skills_show_missing(capsys):
    rc = cli_mod._cmd_skills(_ns(name="no-such-skill-zzz", source=None, limit=None, force=False))
    assert rc == 1


def test_cmd_skills_sync_no_source_errors(capsys, monkeypatch):
    # ensure no hermes-shaped local source is auto-detected
    monkeypatch.setattr("birkin.skills.sync.autodetect_sources", lambda: [])
    rc = cli_mod._cmd_skills(_ns(name="sync", source=None, limit=None, force=False))
    out = capsys.readouterr().out
    assert rc == 1 and "No source" in out


def test_cmd_skills_sync_from_dir(tmp_path: Path, capsys):
    # build a tiny fake upstream
    src = tmp_path / "up"
    skill = src / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: x\n---\nbody\n", encoding="utf-8")
    rc = cli_mod._cmd_skills(_ns(name="sync", source=str(src),
                                 limit=None, force=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "mirrored" in out.lower()


# ---------------- handlers that just delegate (monkeypatch the runners) ----------------

def test_cmd_web_delegates(monkeypatch):
    called = {}
    def fake_run(port=None, *, open_browser=True):
        called["port"] = port; called["open"] = open_browser; return 0
    monkeypatch.setattr("birkin.web.run", fake_run)
    rc = cli_mod._cmd_web(_ns(port=8800, no_browser=True))
    assert rc == 0 and called == {"port": 8800, "open": False}


def test_cmd_gateway_delegates(monkeypatch):
    called = {"v": False}
    monkeypatch.setattr("birkin.gateway.run", lambda: (called.__setitem__("v", True) or 0))
    rc = cli_mod._cmd_gateway(_ns())
    assert rc == 0 and called["v"] is True


def test_cmd_nightly_delegates(monkeypatch):
    called = {}

    def fake_run_once(dry_run=False):
        called["dry"] = dry_run
        return 0
    monkeypatch.setattr("birkin.nightly.run_once", fake_run_once)
    rc = cli_mod._cmd_nightly(_ns(dry_run=True))
    assert rc == 0 and called["dry"] is True


def test_cmd_daemon_install_branch(monkeypatch):
    monkeypatch.setattr("birkin.scheduler.install_os_schedule", lambda: 0)
    monkeypatch.setattr("birkin.scheduler.run_daemon",
                        lambda: (_ for _ in ()).throw(AssertionError("should not run loop")))
    rc = cli_mod._cmd_daemon(_ns(install=True))
    assert rc == 0


def test_cmd_review_delegates(monkeypatch):
    monkeypatch.setattr("birkin.approvals.review_cli", lambda: 0)
    rc = cli_mod._cmd_review(_ns())
    assert rc == 0


def test_cmd_setup_invokes_onboarding(monkeypatch):
    monkeypatch.setattr("birkin.onboarding.run", lambda: 0)
    rc = cli_mod._cmd_setup(_ns())
    assert rc == 0


def test_cmd_model_non_interactive(monkeypatch, capsys):
    rc = cli_mod._cmd_model(_ns(name="claude-opus-4-7"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "claude-opus-4-7" in out


def test_main_dispatches(monkeypatch):
    called = {}

    def fake_skills(args):
        called["ok"] = True
        return 0
    monkeypatch.setattr("birkin.cli._cmd_skills", fake_skills)
    rc = cli_mod.main(["skills"])
    assert rc == 0 and called["ok"]
