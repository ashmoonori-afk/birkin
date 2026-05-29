"""Pluggable gateway channels."""

from __future__ import annotations

import os
from typing import Any

from .base import Channel


def telegram_token(tg: dict[str, Any]) -> str:
    """Resolve the Telegram bot token: env var first, then config (plaintext)."""
    return (os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
            or os.environ.get("BIRKIN_TELEGRAM_TOKEN", "").strip()
            or str(tg.get("token", "")).strip())


def build_channels(cfg: dict[str, Any]) -> list[Channel]:
    """Instantiate the channels enabled in config."""
    channels: list[Channel] = []
    ch = cfg.get("channels", {}) or {}

    if ch.get("http", {}).get("enabled", True):
        from .local_http import LocalHTTPChannel
        channels.append(LocalHTTPChannel(int(cfg.get("gateway_port", 8788))))

    tg = ch.get("telegram", {}) or {}
    if tg.get("enabled"):
        token = telegram_token(tg)
        if not token:
            print("[gateway] telegram enabled but no token "
                  "(set TELEGRAM_BOT_TOKEN or channels.telegram.token) — skipping.")
        else:
            from .telegram import TelegramChannel
            if tg.get("token") and not (os.environ.get("TELEGRAM_BOT_TOKEN")
                                        or os.environ.get("BIRKIN_TELEGRAM_TOKEN")):
                print("[gateway] SECURITY: Telegram token is stored in plaintext in "
                      "config.json. Prefer the TELEGRAM_BOT_TOKEN env var; rotate the "
                      "token via @BotFather if it may have leaked.")
            allowed = [str(c).strip() for c in (tg.get("allowed_chat_ids") or [])
                       if str(c).strip()]
            if not allowed:
                print("[gateway] WARNING: Telegram has no allowed_chat_ids — ANYONE "
                      "who finds the bot can drive the agent. Set "
                      "channels.telegram.allowed_chat_ids to your chat id(s).")
            channels.append(TelegramChannel(token, allowed_chat_ids=allowed))

    return channels


__all__ = ["Channel", "build_channels"]
