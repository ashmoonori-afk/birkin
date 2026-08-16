"""Tests for the gateway /restart-gateway command (soft in-place restart)."""

from __future__ import annotations


class _FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _gateway(tmp_path, monkeypatch, tg_allowed=None):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    # restart() reloads from the config file on disk, so persist one.
    cfg = {**config.DEFAULT_CONFIG, "provider": "claude-cli",
           "gateway_persistent": True}
    if tg_allowed:
        # Privileged commands from Telegram require a closed bot
        # (allowed_chat_ids) — see Gateway._command_trusted.
        cfg["channels"] = {"telegram": {"allowed_chat_ids": list(tg_allowed)}}
    config.save_config(cfg)
    from birkin.gateway.core import Gateway
    return Gateway(config.load_config())


def test_restart_gateway_clears_sessions_and_rebuilds(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    fake = _FakeSession()
    gw._claude_sessions.put(("http", "c1"), fake)
    gw._chats[("http", "c1")] = [{"role": "user", "content": []}]
    prev_session = gw.session

    out = gw.handle("http", "c1", "/restart-gateway")

    assert "restart" in out.lower()
    assert fake.closed is True              # warm session torn down
    assert len(gw._claude_sessions) == 0    # all warm sessions cleared
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


def test_restart_preserves_gateway_goal_isolation(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    from birkin import goals, promptgate
    from birkin.gateway.core import conversation_session_id

    goals.set_goal("PRIVATE OPERATOR GOAL")
    session_id = conversation_session_id("telegram", "stranger")
    assert "PRIVATE OPERATOR GOAL" not in promptgate._goal_note(
        {**gw.cfg, "session_id": session_id}
    )

    monkeypatch.setattr(gw, "prewarm", lambda: None)
    with gw._lock:
        gw.restart()

    assert gw.cfg["session_goal_fallback"] is False
    assert "PRIVATE OPERATOR GOAL" not in promptgate._goal_note(
        {**gw.cfg, "session_id": session_id}
    )


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


def test_hard_restart_records_origin_and_writes_greeting_marker(tmp_path, monkeypatch):
    import os
    gw = _gateway(tmp_path, monkeypatch, tg_allowed=["555"])
    gw.handle("telegram", "555", "/hard-restart")
    assert gw._restart_origin == ("telegram", "555")
    monkeypatch.setattr(gw, "shutdown", lambda: None)
    monkeypatch.setattr(os, "execv", lambda path, argv: None)
    gw.do_hard_restart()                              # writes the marker, stubbed exec
    from birkin import store
    from birkin.gateway.core import _restart_marker_path
    assert store._read_json(_restart_marker_path(), None) == {
        "channel": "telegram", "chat_id": "555"}


def test_take_restart_greeting_is_channel_scoped_and_one_shot(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    gw._restart_notice = {"channel": "telegram", "chat_id": "99"}
    assert gw.take_restart_greeting("http") is None      # wrong channel -> no greet
    assert gw.take_restart_greeting("telegram") == "99"  # matching channel
    assert gw.take_restart_greeting("telegram") is None  # consumed (one-shot)


def test_models_restart_records_origin(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch, tg_allowed=["7"])
    gw.handle("telegram", "7", "/models opus")           # schedules a hard restart
    assert gw.pending_hard_restart is True
    assert gw._restart_origin == ("telegram", "7")


def test_soft_restart_reply_includes_greeting(tmp_path, monkeypatch):
    # Soft /restart returns synchronously, so the greeting is appended to its reply
    # (same friendly tail as the hard-restart greeting).
    from birkin.gateway.core import _BACK_GREETING
    gw = _gateway(tmp_path, monkeypatch)
    out = gw.handle("http", "c1", "/restart")
    assert "restarted" in out.lower() and _BACK_GREETING in out


# -- /update (remote code pull + auto restart) -----------------------------

def test_match_command_recognizes_update_variants():
    from birkin.gateway.core import match_command
    for t in ("/update", "/upgrade", "/pull", "/UPDATE", "/update@birkinbot"):
        assert match_command(t)[0] == "update", t


def test_update_triggers_hard_restart_when_code_changed(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch, tg_allowed=["42"])
    import birkin.updater as updater
    monkeypatch.setattr(updater, "update",
                        lambda *a, **k: {"ok": True, "updated": True,
                                         "message": "Updated 2 commit(s)."})
    out = gw.handle("telegram", "42", "/update")
    assert "Updated 2 commit" in out
    assert gw.pending_hard_restart is True               # re-exec scheduled to load new code
    assert gw._restart_origin == ("telegram", "42")


def test_privileged_commands_refused_on_open_telegram(tmp_path, monkeypatch):
    """An OPEN Telegram bot (no allowed_chat_ids) must refuse privileged
    commands — a stranger must not be able to pull code or restart the
    service (Gateway._command_trusted)."""
    gw = _gateway(tmp_path, monkeypatch)                 # no allowed_chat_ids
    for cmd in (
        "/update",
        "/models opus",
        "/hard-restart",
        "/restart",
        "/neurosis inspect shared state",
    ):
        out = gw.handle("telegram", "999", cmd)
        assert "restricted" in out.lower(), cmd
    assert gw.pending_hard_restart is False
    # loopback HTTP stays local/trusted — unaffected by the telegram gate.
    assert "restricted" not in gw.handle("http", "c1", "/restart").lower()


def test_update_no_restart_when_already_latest(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    import birkin.updater as updater
    monkeypatch.setattr(updater, "update",
                        lambda *a, **k: {"ok": True, "updated": False,
                                         "message": "Already up to date."})
    out = gw.handle("http", "c1", "/update")
    assert "Already up to date" in out
    assert gw.pending_hard_restart is False              # nothing new → no restart


def test_update_reports_failure_without_restart(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    import birkin.updater as updater
    monkeypatch.setattr(updater, "update",
                        lambda *a, **k: {"ok": False, "updated": False,
                                         "message": "Local uncommitted changes present."})
    out = gw.handle("http", "c1", "/update")
    assert "uncommitted" in out.lower()
    assert gw.pending_hard_restart is False
