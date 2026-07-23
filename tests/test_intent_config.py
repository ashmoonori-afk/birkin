"""Regression coverage for intent rollout configuration."""

from __future__ import annotations

import json

import pytest

from birkin import config


def test_existing_config_values_round_trip_unchanged() -> None:
    # Given: an existing configuration using unrelated established settings.
    saved = {
        **config.DEFAULT_CONFIG,
        "model": "sonnet",
        "cli_access": "full",
        "auto_approve": ["cron"],
    }

    # When: it is saved and loaded through the normal atomic path.
    config.save_config(saved)
    loaded = config.load_config()

    # Then: existing settings retain their values.
    assert loaded["model"] == "sonnet"
    assert loaded["cli_access"] == "full"
    assert loaded["auto_approve"] == ["cron"]


@pytest.mark.parametrize(
    ("saved_value", "expected"),
    [
        ("off", "off"),
        ("observe", "observe"),
        ("assist", "assist"),
        ("auto-safe", "auto-safe"),
        (None, "off"),
        (7, "off"),
        ("invalid", "off"),
    ],
)
def test_natural_language_commands_normalizes_saved_values(
    saved_value: str | int | None,
    expected: str,
) -> None:
    # Given: a saved rollout value from an allowed or malformed configuration.
    config.config_path().write_text(
        json.dumps({"natural_language_commands": saved_value}),
        encoding="utf-8",
    )

    # When: the configuration is loaded.
    loaded = config.load_config()

    # Then: only the supported global rollout modes survive.
    assert loaded["natural_language_commands"] == expected


@pytest.mark.parametrize("mode", ["off", "observe", "assist", "auto-safe"])
def test_natural_language_commands_round_trips_valid_modes(mode: str) -> None:
    # Given: a supported rollout mode in an otherwise normal configuration.
    config.save_config({**config.DEFAULT_CONFIG, "natural_language_commands": mode})

    # When: the configuration is loaded after its atomic save.
    loaded = config.load_config()

    # Then: the configured mode is preserved.
    assert loaded["natural_language_commands"] == mode


def test_natural_language_commands_missing_value_defaults_off() -> None:
    # Given: a configuration file with no rollout setting.
    config.config_path().write_text(json.dumps({"model": "sonnet"}), encoding="utf-8")

    # When: the configuration is loaded.
    loaded = config.load_config()

    # Then: the rollout setting is safely disabled.
    assert loaded["natural_language_commands"] == "off"
