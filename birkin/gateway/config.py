"""Configuration persistence for Birkin gateway settings."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from birkin.mcp.types import MCPServerConfig

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("birkin_config.json")

_DEFAULTS: dict[str, Any] = {
    "provider": "anthropic",
    "model": None,
    "fallback_provider": None,
    "fallback_model": None,
    "onboarding_complete": False,
    "system_prompt": None,
    "active_workflow": None,
    "telegram_webhook_secret": None,
    "mcp_servers": [],
}


class BirkinConfig(BaseModel):
    """Schema for birkin_config.json with forward-compatible extra fields."""

    model_config = ConfigDict(extra="allow")

    provider: str = "anthropic"
    model: str | None = None
    fallback_provider: str | None = None
    fallback_model: str | None = None
    onboarding_complete: bool = False
    system_prompt: str | None = None
    active_workflow: str | None = None
    telegram_webhook_secret: str | None = None
    mcp_servers: list[MCPServerConfig] = []


def load_config() -> dict[str, Any]:
    """Load config from disk, validate via BirkinConfig, merge with defaults."""
    config = dict(_DEFAULTS)
    if _CONFIG_PATH.exists():
        try:
            stored = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            validated = BirkinConfig(**stored)
            config.update(validated.model_dump())
        except (json.JSONDecodeError, OSError):
            pass
        except ValidationError as exc:
            logger.warning("Invalid config, using defaults: %s", exc)
    return config


def save_config(config: dict[str, Any]) -> None:
    """Validate config via BirkinConfig, then write to disk."""
    try:
        validated = BirkinConfig(**config)
    except ValidationError as exc:
        logger.warning("Invalid config, refusing to save: %s", exc)
        return
    _CONFIG_PATH.write_text(
        json.dumps(validated.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
