"""Send-only gateway channel registry and webhook adapters."""

from __future__ import annotations

import json
import types

import pytest

from birkin import config
from birkin.gateway import core as gw_core
from birkin.gateway.channels import build_channels


class _Response:
    def __init__(self, status: int = 204):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return b""


def _capture_post(monkeypatch, module):
    seen = {}

    class _Opener:
        @staticmethod
        def open(request, timeout):
            seen["request"] = request
            seen["timeout"] = timeout
            return _Response()

    monkeypatch.setattr(module, "pinned_opener", lambda: _Opener())
    return seen


def test_default_webhook_channels_are_disabled():
    from birkin.gateway.channels.registry import default_registry

    cfg = config.load_config()
    assert cfg["channels"]["slack"]["enabled"] is False
    assert cfg["channels"]["discord"]["enabled"] is False
    assert default_registry.resolve("slack", cfg) is None
    assert default_registry.resolve("discord", cfg) is None


def test_default_webhook_channels_are_labeled_send_only():
    from birkin.gateway.channels.registry import default_registry

    assert default_registry.labels() == (
        "slack (send-only)",
        "discord (send-only)",
    )


def test_registry_contract_and_legacy_fallthrough():
    from birkin.gateway.channels.registry import ChannelEntry, Registry

    made = object()
    entry = ChannelEntry(
        name="custom",
        factory=lambda cfg: made,
        validate_cfg=lambda cfg: [],
        health=lambda: "configured",
        max_message_len=123,
        allowed=lambda target: target == "room-1",
    )
    registry = Registry()
    registry.register(entry)
    fallback_calls = []

    assert registry.names() == ("custom",)
    assert registry.get("custom") is entry
    assert registry.resolve("custom", {}, fallback=lambda name: fallback_calls.append(name)) is made
    assert fallback_calls == []
    assert registry.resolve(
        "telegram", {}, fallback=lambda name: ("legacy", name)
    ) == ("legacy", "telegram")
    assert entry.allowed("room-1") is True
    assert entry.allowed("room-2") is False


def test_gateway_resolves_registry_before_legacy(monkeypatch):
    fake_session = types.SimpleNamespace(cfg={}, agent=types.SimpleNamespace(messages=[]))
    monkeypatch.setattr(gw_core, "build_session", lambda _cfg: fake_session)
    cfg = {
        "channels": {
            "slack": {
                "enabled": True,
                "webhook_url": "https://hooks.slack.com/services/1",
                "allowed_channel_ids": ["ops"],
            }
        }
    }
    gateway = gw_core.Gateway(cfg)
    fallback_calls = []

    adapter = gateway.resolve_delivery_target(
        "slack", fallback=lambda name: fallback_calls.append(name)
    )
    assert adapter is not None
    assert adapter.name == "slack"
    assert fallback_calls == []
    assert gateway.resolve_delivery_target(
        "telegram", fallback=lambda name: ("legacy", name)
    ) == ("legacy", "telegram")


def test_slack_posts_json_and_truncates(monkeypatch):
    from birkin.gateway.channels import slack_webhook

    cfg = {
        "channels": {
            "slack": {
                "enabled": True,
                "webhook_url": "https://hooks.slack.com/services/1",
                "allowed_channel_ids": ["ops"],
            }
        }
    }
    adapter = slack_webhook.SlackWebhookAdapter(cfg)
    seen = _capture_post(monkeypatch, slack_webhook)

    assert adapter.send("ops", "x" * 4000) is True
    request = seen["request"]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == cfg["channels"]["slack"]["webhook_url"]
    assert request.get_header("Content-type") == "application/json"
    assert len(payload["text"]) == 3500
    assert payload["text"].endswith(slack_webhook.TRUNCATION_MARKER)
    assert adapter.health() == "enabled/configured"


def test_discord_posts_json_and_truncates(monkeypatch):
    from birkin.gateway.channels import discord_webhook

    cfg = {
        "channels": {
            "discord": {
                "enabled": True,
                "webhook_url": "https://discord.com/api/webhooks/1",
                "allowed_channel_ids": ["ops"],
            }
        }
    }
    adapter = discord_webhook.DiscordWebhookAdapter(cfg)
    seen = _capture_post(monkeypatch, discord_webhook)

    assert adapter.send("ops", "y" * 2500) is True
    payload = json.loads(seen["request"].data.decode("utf-8"))
    assert len(payload["content"]) == 2000
    assert payload["content"].endswith(discord_webhook.TRUNCATION_MARKER)
    assert adapter.health() == "enabled/configured"


@pytest.mark.parametrize(
    ("module_name", "entry_name"),
    [("slack_webhook", "slack"), ("discord_webhook", "discord")],
)
def test_webhook_validation_is_https_only(module_name, entry_name):
    module = __import__(f"birkin.gateway.channels.{module_name}", fromlist=["entry"])

    assert module.validate_cfg({}) == []  # optional and disabled
    assert module.validate_cfg({"channels": {entry_name: {"enabled": True}}}) == [
        f"channels.{entry_name}.webhook_url is required when enabled"
    ]
    problems = module.validate_cfg(
        {"channels": {entry_name: {"enabled": True, "webhook_url": "http://example.test/hook"}}}
    )
    assert len(problems) == 1
    assert problems[0].startswith(
        f"channels.{entry_name}.webhook_url must use https"
    )


def test_health_never_touches_network(monkeypatch):
    from birkin.gateway.channels import slack_webhook

    monkeypatch.setattr(
        slack_webhook.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("health made a network call"),
    )
    assert slack_webhook.SlackWebhookAdapter({}).health() == "disabled/unconfigured"
    adapter = slack_webhook.SlackWebhookAdapter(
        {"channels": {"slack": {"enabled": True, "webhook_url": "http://bad"}}}
    )
    assert adapter.health() == "enabled/unconfigured"


def test_registered_target_rejects_invalid_config_without_legacy_fallback():
    from birkin.gateway.channels.registry import default_registry

    fallback_calls = []
    resolved = default_registry.resolve(
        "discord",
        {"channels": {"discord": {"enabled": True, "webhook_url": "http://bad"}}},
        fallback=lambda name: fallback_calls.append(name),
    )
    assert resolved is None
    assert fallback_calls == []


def test_redelivery_uses_registered_adapter_before_legacy_send(
        tmp_path, monkeypatch):
    from birkin import delivery
    from birkin.gateway.channels.slack_webhook import SlackWebhookAdapter

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setattr(
        delivery.config,
        "load_config",
        lambda: {
            "channels": {
                "slack": {
                    "enabled": True,
                    "webhook_url": "https://hooks.slack.com/services/1",
                }
            }
        },
    )
    sent = []
    monkeypatch.setattr(
        SlackWebhookAdapter,
        "send",
        lambda self, target, text: sent.append((target, text)) or True,
    )
    delivery.record("slack", "room-1", "hello")

    assert delivery.redeliver(
        "slack",
        lambda *_args: pytest.fail("legacy sender was used"),
        prefix="",
    ) == 1
    assert sent == [("room-1", "hello")]


def test_legacy_build_channels_is_unchanged_when_webhooks_are_absent():
    cfg = {"gateway_port": 0, "channels": {"http": {"enabled": True}}}
    assert [channel.name for channel in build_channels(cfg)] == ["http"]


def test_build_channels_allows_capability_stripped_open_telegram():
    cfg = {
        "channels": {
            "http": {"enabled": False},
            "telegram": {
                "enabled": True,
                "token": "test-token",
                "allowed_chat_ids": [],
                "allowed_sender_ids": [123, "456"],
                "stream": True,
            },
        },
    }

    channels = build_channels(cfg)

    assert [channel.name for channel in channels] == ["telegram"]
    assert channels[0].allowed_sender_ids == {"123", "456"}
