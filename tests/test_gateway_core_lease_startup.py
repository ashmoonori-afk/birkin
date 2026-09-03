"""A taken Telegram lease must end startup with an operator message, not a trace."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin.gateway import core
from birkin.gateway.telegram_lease import (
    TelegramGatewayLeaseRaceError,
    TelegramGatewayOwnedError,
)


def _lock_path(tmp_path: Path) -> Path:
    return tmp_path / "gateway-locks" / "telegram-abc123def456.json"


def _refuse_gateway(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    def build(_cfg: object) -> object:
        raise error

    monkeypatch.setattr(core, "install_timestamped_logging", lambda: None)
    monkeypatch.setattr(core, "Gateway", build)


def test_run_reports_the_owning_pid_and_lock_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: a second gateway starts while a live process owns the same bot.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    lock = _lock_path(tmp_path)
    _refuse_gateway(
        monkeypatch,
        TelegramGatewayOwnedError(4321, "abc123def456", lock),
    )

    # When
    exit_code = core.run()

    # Then: it exits 1 naming the owner and the lock file to clear.
    assert exit_code == 1
    printed = capsys.readouterr().out
    assert "4321" in printed
    assert str(lock) in printed


def test_run_reports_a_lease_race_with_the_lock_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: ownership kept changing while this process tried to claim it.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    lock = _lock_path(tmp_path)
    _refuse_gateway(monkeypatch, TelegramGatewayLeaseRaceError(lock))

    # When
    exit_code = core.run()

    # Then
    assert exit_code == 1
    assert str(lock) in capsys.readouterr().out
