from __future__ import annotations

import json
from pathlib import Path

import pytest

from birkin import config


def test_validated_config_set_persists_requested_and_effective(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))

    result = config.set_config("max_turns", 12)

    assert result.accepted is True
    assert result.requested == {"key": "max_turns", "value": 12}
    assert result.effective == {"key": "max_turns", "value": 12}
    assert result.reason is None
    assert config.load_config()["max_turns"] == 12


def test_validated_config_set_rejects_without_partial_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    path = config.save_config({**config.load_config(), "max_turns": 8})
    before = path.read_bytes()

    result = config.set_config("max_turns", "many")

    assert result.accepted is False
    assert result.requested == {"key": "max_turns", "value": "many"}
    assert result.effective == {"key": "max_turns", "value": 8}
    assert result.reason and "invalid config" in result.reason
    assert path.read_bytes() == before
    assert json.loads(path.read_text())["max_turns"] == 8
