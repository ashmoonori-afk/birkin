"""Pluggable gateway channels."""

from __future__ import annotations

import os
from typing import Any

from .base import Channel
from .registry import (
    ChannelEntry,
    Registry,
    default_registry,
    get,
    names,
    register,
    resolve_delivery_target,
)


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
        gateway_cfg = cfg.get("gateway", {}) or {}
        gateway_http = (
            gateway_cfg.get("http", {})
            if isinstance(gateway_cfg, dict)
            else {}
        )
        insecure_no_token = bool(
            gateway_http.get("insecure_no_token", False)
            if isinstance(gateway_http, dict)
            else False
        )
        channels.append(
            LocalHTTPChannel(
                int(cfg.get("gateway_port", 8788)),
                insecure_no_token=insecure_no_token,
            )
        )

    tg = ch.get("telegram", {}) or {}
    if tg.get("enabled"):
        token = telegram_token(tg)
        if not token:
            print("[gateway] telegram enabled but no token "
                  "(set TELEGRAM_BOT_TOKEN or channels.telegram.token) — skipping.")
        else:
            if tg.get("token") and not (os.environ.get("TELEGRAM_BOT_TOKEN")
                                        or os.environ.get("BIRKIN_TELEGRAM_TOKEN")):
                print("[gateway] SECURITY: Telegram token is stored in plaintext in "
                      "config.json. Prefer the TELEGRAM_BOT_TOKEN env var; rotate the "
                      "token via @BotFather if it may have leaked.")
            allowed = [str(c).strip() for c in (tg.get("allowed_chat_ids") or [])
                       if str(c).strip()]
            if not allowed:
                print("[gateway] Telegram is public and capability-stripped: "
                      "configure allowed_chat_ids for trusted turns.")
            from .polished_telegram import PolishedTelegramChannel
            channels.append(PolishedTelegramChannel(
                token, cfg=cfg, allowed_chat_ids=allowed,
                stream=bool(tg.get("stream", True)),
                max_public_workers=int(
                    tg.get("max_public_workers", 4)
                )))

    return channels


__all__ = [
    "Channel",
    "ChannelEntry",
    "Registry",
    "build_channels",
    "default_registry",
    "get",
    "names",
    "register",
    "resolve_delivery_target",
]
