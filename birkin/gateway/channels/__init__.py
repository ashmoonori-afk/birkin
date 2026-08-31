"""Pluggable gateway channels."""

from __future__ import annotations

import os

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
from .registry_types import Config, JsonValue


def _config_mapping(value: JsonValue) -> Config:
    """Treat a JSON object as a channel configuration mapping."""
    return value if isinstance(value, dict) else {}


def _config_int(value: JsonValue, default: int) -> int:
    """Convert supported JSON scalar configuration values to an integer."""
    if isinstance(value, (str, int, float)):
        return int(value)
    return default


def telegram_token(tg: Config) -> str:
    """Resolve the Telegram bot token: env var first, then config (plaintext)."""
    return (
        os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        or os.environ.get("BIRKIN_TELEGRAM_TOKEN", "").strip()
        or str(tg.get("token", "")).strip()
    )


def build_channels(cfg: Config) -> list[Channel]:
    """Instantiate the channels enabled in config."""
    channels: list[Channel] = []
    ch = _config_mapping(cfg.get("channels"))

    http_cfg = _config_mapping(ch.get("http"))
    if bool(http_cfg.get("enabled", True)):
        from .local_http import LocalHTTPChannel

        gateway_cfg = _config_mapping(cfg.get("gateway"))
        gateway_http = _config_mapping(gateway_cfg.get("http"))
        insecure_no_token = bool(gateway_http.get("insecure_no_token", False))
        channels.append(
            LocalHTTPChannel(
                _config_int(cfg.get("gateway_port", 8788), 8788),
                insecure_no_token=insecure_no_token,
            )
        )

    tg = _config_mapping(ch.get("telegram"))
    if bool(tg.get("enabled")):
        token = telegram_token(tg)
        if not token:
            print(
                "[gateway] telegram enabled but no token "
                + "(set TELEGRAM_BOT_TOKEN or channels.telegram.token) — skipping."
            )
        else:
            if tg.get("token") and not (
                os.environ.get("TELEGRAM_BOT_TOKEN")
                or os.environ.get("BIRKIN_TELEGRAM_TOKEN")
            ):
                print(
                    "[gateway] SECURITY: Telegram token is stored in plaintext in "
                    + "config.json. Prefer the TELEGRAM_BOT_TOKEN env var; rotate the "
                    + "token via @BotFather if it may have leaked."
                )
            raw_allowed = tg.get("allowed_chat_ids")
            allowed = (
                [
                    str(chat_id).strip()
                    for chat_id in raw_allowed
                    if str(chat_id).strip()
                ]
                if isinstance(raw_allowed, list)
                else []
            )
            raw_allowed_senders = tg.get("allowed_sender_ids")
            allowed_senders = (
                [
                    str(sender_id).strip()
                    for sender_id in raw_allowed_senders
                    if str(sender_id).strip()
                ]
                if isinstance(raw_allowed_senders, list)
                else []
            )
            if not allowed:
                print(
                    "[gateway] Telegram is public and capability-stripped: "
                    + "configure allowed_chat_ids for trusted turns."
                )
            from .polished_telegram import PolishedTelegramChannel

            polish_cfg = {
                key: value
                for key, value in cfg.items()
                if isinstance(value, (str, int)) or value is None
            }
            channels.append(
                PolishedTelegramChannel(
                    token,
                    cfg=polish_cfg,
                    allowed_chat_ids=allowed,
                    allowed_sender_ids=allowed_senders,
                    stream=bool(tg.get("stream", True)),
                    max_public_workers=_config_int(tg.get("max_public_workers", 4), 4),
                )
            )

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
