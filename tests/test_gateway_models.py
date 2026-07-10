"""Tests for /models — gateway model selector + auto hard-restart, and REPL select."""

from __future__ import annotations

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


def _fake_repl_session(cfg):
    reloaded = {"n": 0}
    sess = types.SimpleNamespace(
        cfg=cfg, client=types.SimpleNamespace(model=cfg.get("model")),
        reload_client=lambda: reloaded.__setitem__("n", reloaded["n"] + 1))
    return sess, reloaded


def test_repl_models_select_rewires_provider_live(tmp_path, monkeypatch):
    # Selecting a claude-cli model FROM a codex session must switch the provider
    # to claude-cli (not leave codex pointed at a claude id) and rebuild the
    # live client. This is the bug: `/models` used to set only the model string.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import models, slashcommands
    monkeypatch.setattr(models, "discover", lambda cfg, **k: [
        models.Model("claude-code (opus)", "claude-cli", "local CLI", param="opus"),
        models.Model("claude-sonnet-5", "anthropic", "api"),
    ])
    sess, reloaded = _fake_repl_session({"provider": "codex-cli", "model": "gpt-5.5"})
    slashcommands._models(sess, "opus")            # name -> the claude-cli entry
    assert sess.cfg["provider"] == "claude-cli"    # provider rewired (fix)
    assert sess.cfg["model"] == "opus"
    assert reloaded["n"] == 1                       # live client rebuilt


def test_repl_models_select_by_number(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import models, slashcommands
    monkeypatch.setattr(models, "discover", lambda cfg, **k: [
        models.Model("claude-sonnet-5", "anthropic", "api"),          # #1
        models.Model("claude-code (opus)", "claude-cli", "", param="opus"),  # #2
    ])
    sess, reloaded = _fake_repl_session({"provider": "claude-cli", "model": "sonnet"})
    slashcommands._models(sess, "1")               # pick #1 -> anthropic API model
    assert sess.cfg["provider"] == "anthropic"
    assert sess.cfg["model"] == "claude-sonnet-5"
    assert reloaded["n"] == 1
