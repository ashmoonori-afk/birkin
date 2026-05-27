"""Pluggable gateway channels."""

from __future__ import annotations

from typing import Any

from .base import Channel


def build_channels(cfg: dict[str, Any]) -> list[Channel]:
    """Instantiate the channels enabled in config."""
    channels: list[Channel] = []
    ch = cfg.get("channels", {}) or {}

    if ch.get("http", {}).get("enabled", True):
        from .local_http import LocalHTTPChannel
        channels.append(LocalHTTPChannel(int(cfg.get("gateway_port", 8788))))

    tg = ch.get("telegram", {}) or {}
    if tg.get("enabled") and tg.get("token"):
        from .telegram import TelegramChannel
        channels.append(TelegramChannel(tg["token"]))

    return channels


__all__ = ["Channel", "build_channels"]
