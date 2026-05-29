"""Tests for the gateway /restart-gateway command (soft in-place restart)."""

from __future__ import annotations


class _FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    # restart() reloads from the config file on disk, so persist one.
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                        "gateway_persistent": True})
    from birkin.gateway.core import Gateway
    return Gateway(config.load_config())


def test_restart_gateway_clears_sessions_and_rebuilds(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    fake = _FakeSession()
    gw._claude_sessions[("http", "c1")] = fake
    gw._chats[("http", "c1")] = [{"role": "user", "content": []}]
    prev_session = gw.session

    out = gw.handle("http", "c1", "/restart-gateway")

    assert "restart" in out.lower()
    assert fake.closed is True              # warm session torn down
    assert gw._claude_sessions == {}        # all warm sessions cleared
    assert gw._chats == {}                   # conversations reset
    assert gw.session is not prev_session    # session rebuilt
    assert gw.session is not None


def test_restart_alias(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    out = gw.handle("http", "c1", "/restart")
    assert "restart" in out.lower()


def test_restart_reloads_cli_access_safety(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    # Simulate a config that later turns dangerous; restart must keep it safe.
    import birkin.config as config
    monkeypatch.setattr(config, "load_config",
                        lambda: {"provider": "claude-cli", "cli_access": "full",
                                 "gateway_persistent": True})
    gw.handle("http", "c1", "/restart-gateway")
    assert gw.cfg["cli_access"] == "workspace"


def test_hard_restart_sets_flag_without_execing(tmp_path, monkeypatch):
    """handle() must only FLAG a hard restart — the channel re-execs after reply."""
    gw = _gateway(tmp_path, monkeypatch)
    assert gw.pending_hard_restart is False
    out = gw.handle("http", "c1", "/hard-restart")
    assert "hard restart" in out.lower()
    assert gw.pending_hard_restart is True  # flagged, NOT yet re-executed


def test_hard_restart_aliases(tmp_path, monkeypatch):
    for cmd in ("/restart-hard", "/restart-gateway --hard", "/restart --hard"):
        gw = _gateway(tmp_path, monkeypatch)
        gw.handle("http", "c1", cmd)
        assert gw.pending_hard_restart is True


def test_match_command_tolerates_variants():
    from birkin.gateway.core import match_command
    for t in ("/restart", "/restart-gateway", "/restart_gateway",
              "/restart-gateway@birkinbot", "/RESTART", "/reload"):
        assert match_command(t)[0] == "restart", t
    for t in ("/hard-restart", "/hard_restart", "/restart-hard",
              "/restart-gateway --hard", "/restart hard", "/hardrestart"):
        assert match_command(t)[0] == "hard_restart", t
    assert match_command("/new")[0] == "new"
    assert match_command("/reset")[0] == "new"
    assert match_command("/help")[0] == "help"
    assert match_command("/start")[0] == "help"
    assert match_command("hello there")[0] is None      # not a command
    assert match_command("/unknowncmd")[0] is None


def test_help_lists_commands(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    out = gw.handle("http", "c1", "/help")
    for c in ("/help", "/new", "/restart", "/hard_restart"):
        assert c in out


def test_hyphen_restart_gateway_actually_restarts(tmp_path, monkeypatch):
    """Regression: '/restart-gateway' (with the dash) must be recognised."""
    gw = _gateway(tmp_path, monkeypatch)
    out = gw.handle("http", "c1", "/restart-gateway")
    assert "restart" in out.lower()
    assert gw.pending_hard_restart is False             # soft, not hard


def test_command_menu_valid_for_telegram():
    import re
    from birkin.gateway.core import command_menu
    menu = command_menu()
    assert {m["command"] for m in menu} >= {"help", "new", "restart", "hard_restart"}
    for m in menu:  # Telegram requires [a-z0-9_], 1-32 chars + a description
        assert re.fullmatch(r"[a-z0-9_]{1,32}", m["command"]), m["command"]
        assert m["description"].strip()


def test_do_hard_restart_reexecs_birkin_gateway(tmp_path, monkeypatch):
    import os
    import sys
    gw = _gateway(tmp_path, monkeypatch)
    captured = {}
    monkeypatch.setattr(gw, "shutdown", lambda: captured.setdefault("shutdown", True))
    monkeypatch.setattr(os, "execv",
                        lambda path, argv: captured.update(path=path, argv=argv))
    gw.do_hard_restart()
    assert captured["shutdown"] is True               # warm sessions torn down first
    assert captured["path"] == sys.executable
    assert captured["argv"] == [sys.executable, "-m", "birkin", "gateway"]
