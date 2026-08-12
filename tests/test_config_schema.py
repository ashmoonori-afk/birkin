from __future__ import annotations

import json
import warnings

import pytest

from birkin import config
from birkin.config_model import (
    CONFIG_SCHEMA_VERSION,
    defaults_from_schema,
    load_config_schema,
)


def test_schema_defaults_exactly_match_runtime_defaults() -> None:
    schema = load_config_schema(config.DEFAULT_CONFIG)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["x-birkin-version"] == CONFIG_SCHEMA_VERSION == 1
    assert defaults_from_schema(schema) == config.DEFAULT_CONFIG


def test_invalid_known_values_warn_without_leaking_values(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    secret = "do-not-print-this-secret"
    config.config_path().write_text(json.dumps({
        "max_turns": "many",
        "channels": {"telegram": {
            "token": secret,
            "stream": "yes",
        }},
    }), encoding="utf-8")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        loaded = config.load_config()

    assert loaded["max_turns"] == config.DEFAULT_CONFIG["max_turns"]
    assert loaded["channels"]["telegram"]["stream"] is True
    assert loaded["channels"]["telegram"]["token"] == secret
    messages = "\n".join(str(item.message) for item in caught)
    assert "$.max_turns" in messages
    assert "$.channels.telegram.stream" in messages
    assert secret not in messages


def test_partial_nested_override_preserves_default_siblings(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    config.config_path().write_text(
        json.dumps({"voice": {"wake_phrase": "Computer"}}),
        encoding="utf-8",
    )

    loaded = config.load_config()

    assert loaded["voice"]["wake_phrase"] == "Computer"
    assert loaded["voice"]["sample_rate"] == 24000


def test_unknown_extension_keys_survive_normalization(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    config.config_path().write_text(
        json.dumps({"future_feature": {"enabled": True}}),
        encoding="utf-8",
    )

    assert config.load_config()["future_feature"] == {"enabled": True}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("shell_approval", "manual"),
        ("shell_approval", "smart"),
        ("shell_approval", "off"),
        ("repl_typed_line", "steer"),
        ("repl_typed_line", "kill"),
    ],
)
def test_supported_config_modes_survive_normalization(
    tmp_path, monkeypatch, key, value,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    config.config_path().write_text(
        json.dumps({key: value}),
        encoding="utf-8",
    )

    assert config.load_config()[key] == value


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("auto_approve", [1]),
        ("api_keys", ["valid", 2]),
    ],
)
def test_invalid_array_elements_fall_back_atomically(
    tmp_path, monkeypatch, key, value,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    config.config_path().write_text(
        json.dumps({key: value}),
        encoding="utf-8",
    )

    with pytest.warns(RuntimeWarning, match=key):
        loaded = config.load_config()

    assert loaded[key] == config.DEFAULT_CONFIG[key]
