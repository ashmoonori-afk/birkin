from __future__ import annotations

from types import ModuleType

import pytest

from birkin.gateway.channels import discord_webhook, slack_webhook


class _Response:
    status = 204

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    @staticmethod
    def read() -> bytes:
        return b""


class _Opener:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def open(self, request: object, timeout: int) -> _Response:
        self.requests.append((request, timeout))
        return _Response()


@pytest.mark.parametrize(
    ("module", "channel", "url", "expected"),
    [
        (
            slack_webhook,
            "slack",
            "https://example.invalid/services/1",
            "hooks.slack.com",
        ),
        (
            discord_webhook,
            "discord",
            "https://example.invalid/api/webhooks/1",
            "discord.com",
        ),
    ],
)
def test_webhook_configuration_rejects_unapproved_hosts(
    module: ModuleType,
    channel: str,
    url: str,
    expected: str,
) -> None:
    problems = module.validate_cfg(
        {
            "channels": {
                channel: {
                    "enabled": True,
                    "webhook_url": url,
                }
            }
        }
    )

    assert len(problems) == 1
    assert expected in problems[0]


@pytest.mark.parametrize(
    ("module", "adapter_type", "channel", "url"),
    [
        (
            slack_webhook,
            slack_webhook.SlackWebhookAdapter,
            "slack",
            "https://hooks.slack.com/services/1",
        ),
        (
            discord_webhook,
            discord_webhook.DiscordWebhookAdapter,
            "discord",
            "https://discord.com/api/webhooks/1",
        ),
    ],
)
def test_webhook_send_uses_the_shared_pinned_opener(
    module: ModuleType,
    adapter_type: type,
    channel: str,
    url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opener = _Opener()
    monkeypatch.setattr(
        module,
        "pinned_opener",
        lambda: opener,
        raising=False,
    )
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail(
            "webhook used the default URL opener"
        ),
    )
    adapter = adapter_type(
        {
            "channels": {
                channel: {
                    "enabled": True,
                    "webhook_url": url,
                    "allowed_channel_ids": ["ops"],
                }
            }
        }
    )

    assert adapter.send("ops", "hello") is True
    assert len(opener.requests) == 1
