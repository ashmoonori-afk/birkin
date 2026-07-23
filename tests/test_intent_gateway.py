from __future__ import annotations

import types


class _ToolClient:
    provider = "openai"
    model = "test"

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete(self, **_kwargs):
        self.calls += 1
        return {"content": [{"type": "tool_use", "name": "resolve_command",
                             "input": self.payload}]}


def _gateway(tmp_path, monkeypatch, *, trusted=False):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    cfg = {**config.DEFAULT_CONFIG, "provider": "claude-cli",
           "gateway_persistent": False,
           "natural_language_commands": "auto-safe"}
    if trusted:
        cfg["channels"] = {"telegram": {"allowed_chat_ids": ["42"]}}
    config.save_config(cfg)
    from birkin.gateway.core import Gateway
    gateway = Gateway(config.load_config())
    gateway.session.ask = lambda *_args, **_kwargs: "chat fallback"
    return gateway


def _engine(gateway, payload):
    from birkin.gateway.core import _GatewayPending
    from birkin.intents import IntentEngine
    client = _ToolClient(payload)
    gateway._intent_engine = IntentEngine(
        gateway.cfg, client,
        {"help", "models", "restart", "remind", "pending", "neurosis"},
        surface="gateway", audit=None)
    gateway._intent_engine._pending = _GatewayPending()
    return client


def test_natural_safe_help_enters_existing_gateway_branch(tmp_path, monkeypatch):
    gateway = _gateway(tmp_path, monkeypatch)
    client = _engine(gateway, {"kind": "action", "action": "help",
                               "argument": "", "question": ""})

    reply = gateway.handle("http", "one", "show help")

    assert "/help" in reply
    assert client.calls == 1


def test_natural_restart_requires_confirmation_then_uses_existing_branch(
        tmp_path, monkeypatch):
    gateway = _gateway(tmp_path, monkeypatch)
    _engine(gateway, {"kind": "action", "action": "restart",
                      "argument": "", "question": ""})

    preview = gateway.handle("http", "one", "restart gateway")
    reply = gateway.handle("http", "one", "yes")

    assert "restart" in preview.lower()
    assert "restarted" in reply.lower()


def test_open_telegram_rejects_privileged_natural_action_before_preview(
        tmp_path, monkeypatch):
    gateway = _gateway(tmp_path, monkeypatch)
    _engine(gateway, {"kind": "action", "action": "restart",
                      "argument": "", "question": ""})

    reply = gateway.handle("telegram", "99", "restart gateway")

    assert "restricted" in reply.lower()
    assert gateway._intent_engine.pending("telegram:99") is None
    assert gateway._intent_engine._pending == {}


def test_open_telegram_natural_neurosis_keeps_confirmation_state(
        tmp_path, monkeypatch):
    gateway = _gateway(tmp_path, monkeypatch)
    _engine(gateway, {"kind": "action", "action": "neurosis",
                      "argument": "private idea", "question": ""})
    captured = {}

    def ask(text, **_kwargs):
        captured["text"] = text
        return "started"

    gateway.session.ask = ask

    preview = gateway.handle("telegram", "99", "interview private idea")
    assert "confirm" in preview.lower()
    assert gateway._intent_engine.pending("telegram:99") is not None
    reply = gateway.handle("telegram", "99", "yes")

    assert gateway._intent_engine.pending("telegram:99") is None
    assert reply == "started"
    assert "private idea" in captured["text"]


def test_natural_neurosis_redacts_retained_success_sinks(tmp_path, monkeypatch):
    gateway = _gateway(tmp_path, monkeypatch)
    _engine(gateway, {"kind": "action", "action": "neurosis",
                      "argument": "secret product alpha", "question": ""})
    activity = []
    transcript = []
    captured = {}
    monkeypatch.setattr("birkin.gateway.core.store.append_activity", activity.append)
    monkeypatch.setattr("birkin.transcripts.append_turn",
                        lambda *_args, **_kwargs: transcript.append(_args))

    def ask(text, **kwargs):
        captured["text"] = text
        captured["kwargs"] = kwargs
        return "secret product alpha echoed"

    gateway.session.ask = ask
    gateway.handle("http", "one", "interview secret product alpha")
    reply = gateway.handle("http", "one", "yes")

    assert reply == "secret product alpha echoed"
    assert "secret product alpha" in captured["text"]
    retained = captured["kwargs"]["retained_replacements"]
    assert any(source == "secret product alpha" for source, _replacement in retained)
    assert all("secret product alpha" not in value for value in activity)
    assert all("secret product alpha" not in str(value) for value in transcript)


def test_natural_neurosis_redacts_raw_error(tmp_path, monkeypatch, capsys):
    gateway = _gateway(tmp_path, monkeypatch)
    _engine(gateway, {"kind": "action", "action": "neurosis",
                      "argument": "secret product beta", "question": ""})

    def broken_ask(_text, **_kwargs):
        raise RuntimeError("secret product beta provider failure")

    gateway.session.ask = broken_ask
    gateway.handle("http", "one", "interview secret product beta")
    reply = gateway.handle("http", "one", "yes")

    assert reply
    assert "secret product beta" not in capsys.readouterr().out


def test_literal_unknown_slash_bypasses_classifier_and_cancels_preview(
        tmp_path, monkeypatch):
    gateway = _gateway(tmp_path, monkeypatch)
    client = _engine(gateway, {"kind": "action", "action": "restart",
                               "argument": "", "question": ""})

    gateway.handle("http", "one", "restart gateway")
    gateway.handle("http", "one", "/unknown-command")

    assert client.calls == 1
    assert gateway._intent_engine.pending("http:one") is None


def test_confirmation_state_isolated_by_channel_and_chat(tmp_path, monkeypatch):
    gateway = _gateway(tmp_path, monkeypatch)
    _engine(gateway, {"kind": "action", "action": "restart",
                      "argument": "", "question": ""})

    gateway.handle("http", "one", "restart gateway")
    other = gateway.handle("http", "two", "yes")
    reply = gateway.handle("http", "one", "yes")

    assert "restarted" not in other.lower()
    assert "restarted" in reply.lower()


def test_legacy_gateway_session_without_intent_capabilities_still_chats(
        monkeypatch):
    from birkin.gateway import core
    agent = types.SimpleNamespace(messages=[])
    session = types.SimpleNamespace(agent=agent, ask=lambda text: f"legacy:{text}")
    monkeypatch.setattr(core, "build_session", lambda _cfg: session)

    gateway = core.Gateway({"gateway_persistent": False})

    assert gateway.handle("http", "one", "hello") == "legacy:hello"


def test_legacy_kwargs_session_keeps_existing_gateway_context(monkeypatch):
    from birkin.gateway import core
    agent = types.SimpleNamespace(messages=[])
    captured = {}

    def ask(text, **kwargs):
        captured["text"] = text
        captured["kwargs"] = kwargs
        return "legacy"

    session = types.SimpleNamespace(agent=agent, ask=ask)
    monkeypatch.setattr(core, "build_session", lambda _cfg: session)
    gateway = core.Gateway({"gateway_persistent": False})

    assert gateway.handle("http", "one", "hello") == "legacy"
    assert captured == {
        "text": "hello",
        "kwargs": {"review_skills": True, "route_query": "hello"},
    }


def test_legacy_gateway_session_keeps_friendly_error(monkeypatch):
    from birkin.gateway import core
    agent = types.SimpleNamespace(messages=[])

    def ask(_text):
        raise RuntimeError("legacy /secret/path")

    session = types.SimpleNamespace(agent=agent, ask=ask)
    monkeypatch.setattr(core, "build_session", lambda _cfg: session)
    gateway = core.Gateway({"gateway_persistent": False})

    reply = gateway.handle("http", "one", "hello")

    assert "secret" not in reply and "legacy" not in reply
