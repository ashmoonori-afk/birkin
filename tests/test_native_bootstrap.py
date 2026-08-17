from __future__ import annotations

import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import NativeProtocolError


class MutableClock:
    def __init__(self) -> None:
        self.now: datetime = datetime(2026, 8, 17, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def test_bootstrap_record_is_private_and_rotates_after_exchange(
    tmp_path: Path,
) -> None:
    store = BootstrapSecretStore(tmp_path)
    first = store.issue()

    capability = store.exchange(first.secret)
    second = store.current()

    assert capability.token
    assert second.secret != first.secret
    assert stat.S_IMODE(store.endpoint_path.stat().st_mode) == 0o600
    with pytest.raises(NativeProtocolError) as exc_info:
        _ = store.exchange(first.secret)
    assert exc_info.value.code == "E_BOOTSTRAP_INVALID"


def test_bootstrap_secret_is_consumed_once_under_concurrency(
    tmp_path: Path,
) -> None:
    store = BootstrapSecretStore(tmp_path)
    record = store.issue()

    def exchange() -> str:
        return store.exchange(record.secret).token

    successes: list[str] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(exchange) for _ in range(2)]
        for future in futures:
            try:
                successes.append(future.result())
            except NativeProtocolError as exc:
                failures.append(exc.code)

    assert len(successes) == 1
    assert failures == ["E_BOOTSTRAP_INVALID"]


def test_expired_bootstrap_secret_fails_closed(tmp_path: Path) -> None:
    clock = MutableClock()
    store = BootstrapSecretStore(
        tmp_path,
        ttl=timedelta(seconds=5),
        now=clock,
    )
    record = store.issue()
    clock.now += timedelta(seconds=6)

    with pytest.raises(NativeProtocolError) as exc_info:
        _ = store.exchange(record.secret)

    assert exc_info.value.code == "E_BOOTSTRAP_EXPIRED"


def test_bootstrap_secret_is_rejected_after_ready_exchange(
    tmp_path: Path,
) -> None:
    store = BootstrapSecretStore(tmp_path)
    record = store.issue()
    capability = store.exchange(record.secret)

    assert store.authenticate_session(capability.token) is True
    assert store.authenticate_session(record.secret) is False


def test_session_capability_renewal_rotates_token_with_hard_ceiling(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    store = BootstrapSecretStore(
        tmp_path,
        capability_ttl=timedelta(seconds=5),
        capability_max_age=timedelta(seconds=12),
        now=clock,
    )
    bootstrap = store.issue()
    first = store.exchange(bootstrap.secret)
    clock.now += timedelta(seconds=4)

    second = store.renew_session(first.token)

    assert second.token != first.token
    assert second.hard_expires_at == first.hard_expires_at
    assert store.authenticate_session(first.token) is False
    assert store.authenticate_session(second.token) is True
    assert second.expires_at == clock.now + timedelta(seconds=5)

    clock.now += timedelta(seconds=4)
    third = store.renew_session(second.token)
    assert third.expires_at == first.hard_expires_at

    clock.now = first.hard_expires_at
    with pytest.raises(NativeProtocolError) as exc_info:
        _ = store.renew_session(third.token)
    assert exc_info.value.code == "E_CAPABILITY_EXPIRED"


def test_session_capability_can_be_revoked_without_disk_state(
    tmp_path: Path,
) -> None:
    store = BootstrapSecretStore(tmp_path)
    capability = store.exchange(store.issue().secret)

    store.revoke_session(capability.token)

    assert store.authenticate_session(capability.token) is False
    persisted = store.endpoint_path.read_text(encoding="utf-8")
    assert capability.token not in persisted
