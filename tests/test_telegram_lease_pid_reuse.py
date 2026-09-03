"""PID identity and the operator's way out when it cannot be established."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import psutil
import pytest

from birkin.approval_execution_codec import JSONValue
from birkin.gateway import telegram_lease
from birkin.gateway.telegram_lease import (
    TelegramGatewayLease,
    TelegramGatewayOwnedError,
)

_TOKEN = "1234567890:pid-reuse-aba"
_FINGERPRINT = hashlib.sha256(_TOKEN.encode("utf-8")).hexdigest()[:12]
_CONFIG: dict[str, JSONValue] = {
    "channels": {
        "telegram": {
            "enabled": True,
            "token": _TOKEN,
            "allowed_chat_ids": ["42"],
        }
    }
}


def _stale_lock(tmp_path: Path, *, process_started_at: float) -> Path:
    lock_root = tmp_path / "gateway-locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    owner_path = lock_root / f"telegram-{_FINGERPRINT}.json"
    _ = owner_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "process_started_at": process_started_at,
                "instance_id": "dead-owner",
                "claimed_at": 1.0,
            }
        ),
        encoding="utf-8",
    )
    return owner_path


def test_pid_reuse_is_not_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the recorded PID is live, but it started at another time entirely.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    owner_path = _stale_lock(tmp_path, process_started_at=1.0)

    # When
    lease = TelegramGatewayLease.acquire_for_config(_CONFIG)

    # Then: the reused PID reads as dead and the lock is reclaimed.
    assert lease is not None
    assert lease.path == owner_path
    lease.release()


def test_undeterminable_owner_names_the_lock_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the owner's create_time is unreadable, so liveness cannot be settled.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    owner_path = _stale_lock(tmp_path, process_started_at=1.0)
    real_process = psutil.Process

    class _DeniedProcess:
        def __init__(self, pid: int | None = None) -> None:
            if pid is not None:
                raise psutil.AccessDenied(pid)
            self._own: psutil.Process = real_process()

        def create_time(self) -> float:
            return self._own.create_time()

    monkeypatch.setattr(telegram_lease.psutil, "Process", _DeniedProcess)

    # When
    with pytest.raises(TelegramGatewayOwnedError) as caught:
        _ = TelegramGatewayLease.acquire_for_config(_CONFIG)

    # Then: the operator is told exactly which lock file to clear.
    assert caught.value.path == owner_path
    assert str(owner_path) in str(caught.value)
