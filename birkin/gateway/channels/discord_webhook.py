"""Send-only Discord webhook adapter (standard library only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .registry import ChannelEntry

MAX_MESSAGE_LEN = 2000
TRUNCATION_MARKER = "\n[truncated]"
_REQUEST_TIMEOUT = 15


def _settings(cfg: dict[str, Any]) -> dict[str, Any]:
    return ((cfg.get("channels", {}) or {}).get("discord", {}) or {})


def _configured_url(url: str) -> bool:
    return urllib.parse.urlsplit(url).scheme.lower() == "https"


def validate_cfg(cfg: dict[str, Any]) -> list[str]:
    settings = _settings(cfg)
    if not settings.get("enabled", False):
        return []
    url = str(settings.get("webhook_url") or "").strip()
    if not url:
        return ["channels.discord.webhook_url is required when enabled"]
    if not _configured_url(url):
        return ["channels.discord.webhook_url must use https"]
    return []


def _truncate(text: str) -> str:
    text = str(text)
    if len(text) <= MAX_MESSAGE_LEN:
        return text
    return text[:MAX_MESSAGE_LEN - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER


class DiscordWebhookAdapter:
    name = "discord"
    max_message_len = MAX_MESSAGE_LEN

    def __init__(self, cfg: dict[str, Any]):
        self._cfg = cfg
        settings = _settings(cfg)
        self.enabled = bool(settings.get("enabled", False))
        self.webhook_url = str(settings.get("webhook_url") or "").strip()
        self.allowed_channel_ids = frozenset(
            str(value) for value in settings.get("allowed_channel_ids", [])
        )

    def allowed(self, channel_id: str) -> bool:
        return (
            self.enabled
            and channel_id in self.allowed_channel_ids
            and not validate_cfg(self._cfg)
        )

    def health(self) -> str:
        configured = _configured_url(self.webhook_url)
        return ("enabled" if self.enabled else "disabled") + "/" + (
            "configured" if configured else "unconfigured")

    def send(self, channel_id: str, text: str) -> bool:
        if not self.allowed(channel_id):
            return False
        body = json.dumps(
            {"content": _truncate(text)}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                    request, timeout=_REQUEST_TIMEOUT) as response:
                status = getattr(response, "status", 200)
                response.read()
                return 200 <= int(status) < 300
        except (urllib.error.URLError, OSError, ValueError):
            return False


def entry() -> ChannelEntry:
    return ChannelEntry(
        name="discord",
        factory=DiscordWebhookAdapter,
        validate_cfg=validate_cfg,
        health=lambda: "available",
        max_message_len=MAX_MESSAGE_LEN,
        allowed=lambda _channel_id: False,
    )


__all__ = [
    "DiscordWebhookAdapter",
    "MAX_MESSAGE_LEN",
    "TRUNCATION_MARKER",
    "entry",
    "validate_cfg",
]
