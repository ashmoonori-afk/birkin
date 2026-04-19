"""Remote control endpoints — Slack and Discord webhook configuration."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api/remote", tags=["remote"])

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(os.environ.get("BIRKIN_CONFIG_PATH", "birkin_config.json"))


def _load_config() -> dict[str, Any]:
    if _CONFIG_PATH.exists():
        try:
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_config(data: dict[str, Any]) -> None:
    existing = _load_config()
    existing.update(data)
    _CONFIG_PATH.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------


@router.get("/slack/status")
async def slack_status() -> dict[str, Any]:
    """Check Slack webhook configuration status."""
    cfg = _load_config()
    url = cfg.get("slack_webhook_url", "") or os.environ.get("SLACK_WEBHOOK_URL", "")
    return {
        "configured": bool(url),
        "channel": cfg.get("slack_channel", ""),
        "webhook_set": bool(url),
    }


@router.post("/slack/configure")
async def slack_configure(body: dict[str, Any]) -> dict[str, str]:
    """Save Slack webhook URL."""
    url = body.get("webhook_url", "").strip()
    channel = body.get("channel", "").strip()

    if not url:
        return {"status": "error", "message": "webhook_url is required"}

    if not url.startswith("https://hooks.slack.com/"):
        return {"status": "error", "message": "Invalid Slack webhook URL"}

    _save_config({"slack_webhook_url": url, "slack_channel": channel})
    os.environ["SLACK_WEBHOOK_URL"] = url
    return {"status": "ok", "message": "Slack webhook configured"}


@router.post("/slack/test")
async def slack_test() -> dict[str, str]:
    """Send a test message to Slack."""
    import httpx

    cfg = _load_config()
    url = cfg.get("slack_webhook_url", "") or os.environ.get("SLACK_WEBHOOK_URL", "")

    if not url:
        return {"status": "error", "message": "Slack webhook not configured"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"text": "Birkin connected successfully!"})
            if resp.status_code == 200:
                return {"status": "ok", "message": "Test message sent"}
            return {"status": "error", "message": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------


@router.get("/discord/status")
async def discord_status() -> dict[str, Any]:
    """Check Discord webhook configuration status."""
    cfg = _load_config()
    url = cfg.get("discord_webhook_url", "") or os.environ.get("DISCORD_WEBHOOK_URL", "")
    return {
        "configured": bool(url),
        "username": cfg.get("discord_username", "Birkin"),
        "webhook_set": bool(url),
    }


@router.post("/discord/configure")
async def discord_configure(body: dict[str, Any]) -> dict[str, str]:
    """Save Discord webhook URL."""
    url = body.get("webhook_url", "").strip()
    username = body.get("username", "Birkin").strip()

    if not url:
        return {"status": "error", "message": "webhook_url is required"}

    if "discord.com/api/webhooks/" not in url:
        return {"status": "error", "message": "Invalid Discord webhook URL"}

    _save_config({"discord_webhook_url": url, "discord_username": username})
    os.environ["DISCORD_WEBHOOK_URL"] = url
    return {"status": "ok", "message": "Discord webhook configured"}


@router.post("/discord/test")
async def discord_test() -> dict[str, str]:
    """Send a test message to Discord."""
    import httpx

    cfg = _load_config()
    url = cfg.get("discord_webhook_url", "") or os.environ.get("DISCORD_WEBHOOK_URL", "")
    username = cfg.get("discord_username", "Birkin")

    if not url:
        return {"status": "error", "message": "Discord webhook not configured"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                json={
                    "content": "Birkin connected successfully!",
                    "username": username,
                },
            )
            if resp.status_code in (200, 204):
                return {"status": "ok", "message": "Test message sent"}
            return {"status": "error", "message": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
