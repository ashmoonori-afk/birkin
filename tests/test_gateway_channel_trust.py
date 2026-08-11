"""Fail-closed trust boundary for public gateway channels."""

from __future__ import annotations

import pytest

from birkin import config
from birkin.gateway import core as gateway_core


def _gateway(tmp_path, monkeypatch, channel_cfg):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    channels = {**config.DEFAULT_CONFIG["channels"], **channel_cfg}
    config.save_config({
        **config.DEFAULT_CONFIG,
        "provider": "claude-cli",
        "gateway_persistent": False,
        "channels": channels,
    })
    return gateway_core.Gateway(config.load_config())


def test_untrusted_public_sender_is_denied_before_dispatch(
        tmp_path, monkeypatch):
    gateway = _gateway(
        tmp_path,
        monkeypatch,
        {"kakao": {"allowed_sender_ids": ["owner"]}},
    )
    monkeypatch.setattr(
        gateway,
        "_models_command",
        lambda _arg: pytest.fail("privileged command dispatch was reached"),
    )
    monkeypatch.setattr(
        gateway.session,
        "ask",
        lambda *_args, **_kwargs: pytest.fail("agent dispatch was reached"),
    )

    privileged = gateway.handle(
        "kakao", "room-1", "/models", sender_id="intruder")
    normal = gateway.handle(
        "kakao", "room-1", "remember this", sender_id="intruder")

    assert privileged == gateway_core.UNTRUSTED_CHANNEL_REPLY
    assert normal == gateway_core.UNTRUSTED_CHANNEL_REPLY


def test_public_channel_requires_allowlisted_sender(tmp_path, monkeypatch):
    gateway = _gateway(
        tmp_path,
        monkeypatch,
        {"kakao": {"allowed_sender_ids": ["owner"]}},
    )
    dispatched = []
    monkeypatch.setattr(
        gateway,
        "_models_command",
        lambda arg: dispatched.append(arg) or "models-ok",
    )

    assert gateway.handle(
        "kakao", "room-1", "/models", sender_id="owner") == "models-ok"
    for sender_id in (None, "", "   ", "intruder"):
        assert gateway.handle(
            "kakao", "room-1", "/models", sender_id=sender_id
        ) == gateway_core.UNTRUSTED_CHANNEL_REPLY

    assert dispatched == [""]


def test_existing_local_and_telegram_trust_contracts_remain(
        tmp_path, monkeypatch):
    gateway = _gateway(
        tmp_path,
        monkeypatch,
        {
            "telegram": {
                "enabled": False,
                "token": "",
                "allowed_chat_ids": ["42"],
                "stream": True,
            },
            "slack": {
                "enabled": True,
                "webhook_url": "https://hooks.slack.test/services/1",
            },
            "discord": {
                "enabled": True,
                "webhook_url": "https://discord.test/api/webhooks/1",
            },
        },
    )
    dispatched = []
    monkeypatch.setattr(
        gateway,
        "_models_command",
        lambda arg: dispatched.append(arg) or "models-ok",
    )

    assert gateway.handle("http", "local", "/models") == "models-ok"
    assert gateway.handle("voice", "local", "/models") == "models-ok"
    assert gateway.handle("repl", "local", "/models") == "models-ok"
    assert gateway.handle("local", "local", "/models") == "models-ok"
    assert gateway.handle("telegram", "42", "/models") == "models-ok"
    assert gateway.handle(
        "telegram", "99", "/models") == gateway_core.UNTRUSTED_CHANNEL_REPLY
    assert gateway.handle(
        "slack", "room", "/models", sender_id="owner"
    ) == gateway_core.UNTRUSTED_CHANNEL_REPLY
    assert gateway.handle(
        "discord", "room", "/models", sender_id="owner"
    ) == gateway_core.UNTRUSTED_CHANNEL_REPLY

    assert dispatched == ["", "", "", "", ""]
