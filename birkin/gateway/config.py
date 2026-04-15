"""Configuration persistence for Birkin gateway settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path("birkin_config.json")

_DEFAULTS: dict[str, Any] = {
    "provider": "anthropic",
    "model": None,
    "fallback_provider": None,
    "fallback_model": None,
    "onboarding_complete": False,
    "system_prompt": None,
    "active_workflow": None,
}


def load_config() -> dict[str, Any]:
    """Load config from disk, merging with defaults."""
    config = dict(_DEFAULTS)
    if _CONFIG_PATH.exists():
        try:
            stored = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            config.update(stored)
        except (json.JSONDecodeError, OSError):
            pass
    return config


def save_config(config: dict[str, Any]) -> None:
    """Write config to disk."""
    _CONFIG_PATH.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
