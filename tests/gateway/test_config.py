"""Tests for birkin.gateway.config — Pydantic schema validation."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from birkin.gateway.config import (
    _DEFAULTS,
    BirkinConfig,
    load_config,
    save_config,
)


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    """Provide a temporary config path and patch _CONFIG_PATH to use it."""
    path = tmp_path / "birkin_config.json"
    with patch("birkin.gateway.config._CONFIG_PATH", path):
        yield path


# --- round-trip ---


def test_valid_config_round_trips(config_file: Path) -> None:
    """A valid config written by save_config is identical after load_config."""
    cfg = {
        "provider": "openai",
        "model": "gpt-4",
        "fallback_provider": "anthropic",
        "fallback_model": "claude-3",
        "onboarding_complete": True,
        "system_prompt": "You are helpful.",
        "active_workflow": "default",
        "telegram_webhook_secret": "secret123",
    }
    save_config(cfg)
    loaded = load_config()
    for key, value in cfg.items():
        assert loaded[key] == value


# --- invalid field type falls back to defaults ---


def test_invalid_field_type_falls_back_to_defaults(config_file: Path, caplog: pytest.LogCaptureFixture) -> None:
    """When a field has a wrong type, load_config returns defaults and logs a warning."""
    config_file.write_text(json.dumps({"provider": 123}), encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        loaded = load_config()
    assert loaded == _DEFAULTS
    assert "Invalid config" in caplog.text


def test_save_config_rejects_invalid_field_type(config_file: Path, caplog: pytest.LogCaptureFixture) -> None:
    """save_config refuses to write when validation fails."""
    with caplog.at_level(logging.WARNING):
        save_config({"provider": 123})
    assert not config_file.exists()
    assert "Invalid config" in caplog.text


# --- extra unknown fields preserved ---


def test_extra_unknown_fields_preserved(config_file: Path) -> None:
    """Unknown keys survive a save/load round-trip (forward compatibility)."""
    cfg = dict(_DEFAULTS, custom_plugin="value", nested={"a": 1})
    save_config(cfg)
    loaded = load_config()
    assert loaded["custom_plugin"] == "value"
    assert loaded["nested"] == {"a": 1}


# --- missing fields filled with defaults ---


def test_missing_fields_filled_with_defaults(config_file: Path) -> None:
    """A minimal JSON file gets all missing keys populated from defaults."""
    config_file.write_text(json.dumps({"provider": "openai"}), encoding="utf-8")
    loaded = load_config()
    assert loaded["provider"] == "openai"
    for key, default_value in _DEFAULTS.items():
        if key == "provider":
            continue
        assert loaded[key] == default_value


# --- BirkinConfig model direct tests ---


def test_birkin_config_defaults() -> None:
    """BirkinConfig() with no args produces the same values as _DEFAULTS."""
    cfg = BirkinConfig()
    dumped = cfg.model_dump()
    for key, value in _DEFAULTS.items():
        assert dumped[key] == value


def test_birkin_config_rejects_bad_type() -> None:
    """BirkinConfig raises ValidationError on wrong types."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BirkinConfig(provider=123)  # type: ignore[arg-type]
