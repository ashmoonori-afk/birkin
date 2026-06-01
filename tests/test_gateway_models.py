"""Tests for /models — gateway model selector + auto hard-restart, and REPL select."""

from __future__ import annotations

import json
import types


def _gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                        "gateway_model": "sonnet", "gateway_persistent": False})
    from birkin.gateway.core import Gateway
    return Gateway(config.load_config())


def test_models_list_no_restart(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    out = gw.handle("http", "c1", "/models")
    assert "sonnet" in out and "사용 가능" in out  # lists current + options
    assert gw.pending_hard_restart is False         # listing never restarts


def test_models_select_sets_config_and_schedules_restart(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    out = gw.handle("http", "c1", "/models opus")
    assert "opus" in out and gw.pending_hard_restart is True   # auto hard-restart
    from birkin import config
    assert config.load_config()["gateway_model"] == "opus"     # persisted


def test_models_select_full_claude_id(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    gw.handle("http", "c1", "/models claude-haiku-4-5-20251001")
    from birkin import config
    assert config.load_config()["gateway_model"] == "claude-haiku-4-5-20251001"
    assert gw.pending_hard_restart is True


def test_models_reject_unknown_no_restart(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    out = gw.handle("http", "c1", "/models bogus-model")
    assert "모르는 모델" in out
    assert gw.pending_hard_restart is False                    # no restart on reject
    from birkin import config
    assert config.load_config()["gateway_model"] == "sonnet"   # unchanged


def test_models_alias_singular(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    out = gw.handle("http", "c1", "/model")          # /model also maps to models
    assert "사용 가능" in out


def test_models_in_command_menu(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin.gateway.core import command_menu
    assert "models" in {m["command"] for m in command_menu()}


def _gateway_codex(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    config.save_config({**config.DEFAULT_CONFIG, "provider": "codex-cli",
                        "gateway_persistent": False})
    from birkin.gateway.core import Gateway
    return Gateway(config.load_config())


def test_models_codex_accepts_model_id(tmp_path, monkeypatch):
    # On the codex backend, /models must accept a codex model id (passthrough),
    # not reject it for not being a claude model.
    gw = _gateway_codex(tmp_path, monkeypatch)
    out = gw.handle("http", "c1", "/models gpt-5-codex")
    assert "gpt-5-codex" in out and gw.pending_hard_restart is True
    from birkin import config
    assert config.load_config()["gateway_model"] == "gpt-5-codex"


def test_models_codex_list_shows_codex_suggestions(tmp_path, monkeypatch):
    gw = _gateway_codex(tmp_path, monkeypatch)
    out = gw.handle("http", "c1", "/models")
    assert "사용 가능" in out and "codex" in out.lower()
    assert "opus" not in out          # not claude suggestions on the codex backend
    assert gw.pending_hard_restart is False


def test_repl_models_select_live(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import slashcommands
    sess = types.SimpleNamespace(cfg={"model": "sonnet"},
                                 client=types.SimpleNamespace(model="sonnet"))
    slashcommands._models(sess, "opus")
    assert sess.cfg["model"] == "opus" and sess.client.model == "opus"
