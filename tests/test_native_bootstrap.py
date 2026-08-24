from __future__ import annotations

import os
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from birkin.native.capability import BootstrapSecretStore, CapabilityScope
from birkin.native.protocol import NativeProtocolError

_SCOPE = CapabilityScope(
    instance_id="test-instance",
    connection_id="test-connection",
    surface="test",
    view_id="test",
)
def _authenticated(store: BootstrapSecretStore, token: str) -> bool:
    return store.authenticate_session(token, scope=_SCOPE)


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

    capability = store.exchange(first.secret, scope=_SCOPE)
    second = store.current()

    assert capability.token
    assert second.secret != first.secret
    if os.name != "nt":
        assert stat.S_IMODE(store.endpoint_path.stat().st_mode) == 0o600
    with pytest.raises(NativeProtocolError) as exc_info:
        _ = store.exchange(first.secret, scope=_SCOPE)
    assert exc_info.value.code == "E_BOOTSTRAP_INVALID"


def test_bootstrap_secret_is_consumed_once_under_concurrency(
    tmp_path: Path,
) -> None:
    store = BootstrapSecretStore(tmp_path)
    record = store.issue()

    def exchange() -> str:
        return store.exchange(record.secret, scope=_SCOPE).token

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
        _ = store.exchange(record.secret, scope=_SCOPE)

    assert exc_info.value.code == "E_BOOTSTRAP_EXPIRED"


def test_bootstrap_secret_is_rejected_after_ready_exchange(
    tmp_path: Path,
) -> None:
    store = BootstrapSecretStore(tmp_path)
    record = store.issue()
    capability = store.exchange(record.secret, scope=_SCOPE)

    assert _authenticated(store, capability.token) is True
    assert _authenticated(store, record.secret) is False


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
    first = store.exchange(bootstrap.secret, scope=_SCOPE)
    clock.now += timedelta(seconds=4)

    second = store.renew_session(first.token)

    assert second.token != first.token
    assert second.hard_expires_at == first.hard_expires_at
    assert _authenticated(store, first.token) is True
    assert _authenticated(store, second.token) is True
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
    capability = store.exchange(store.issue().secret, scope=_SCOPE)

    store.revoke_session(capability.token)

    assert _authenticated(store, capability.token) is False
    persisted = store.endpoint_path.read_text(encoding="utf-8")
    assert capability.token not in persisted


def test_session_capability_is_bound_to_connection_scope(
    tmp_path: Path,
) -> None:
    store = BootstrapSecretStore(tmp_path)
    capability = store.exchange(
        store.issue().secret,
        scope=CapabilityScope(
            instance_id="instance-1",
            connection_id="connection-1",
            surface="macos",
            view_id="main",
        ),
    )

    assert store.authenticate_session(
        capability.token,
        scope=capability.scope,
    )
    assert not store.authenticate_session(
        capability.token,
        scope=CapabilityScope(
            instance_id="instance-1",
            connection_id="connection-2",
            surface="macos",
            view_id="main",
        ),
    )
    renewed = store.renew_session(capability.token)
    assert renewed.scope.instance_id == "instance-1"
    assert renewed.scope.connection_id == "connection-1"
    assert renewed.scope.surface == "macos"
    assert renewed.scope.view_id == "main"


def test_renewal_overlap_preserves_exact_scope_for_both_tokens(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    store = BootstrapSecretStore(
        tmp_path,
        capability_ttl=timedelta(seconds=30),
        capability_max_age=timedelta(seconds=90),
        now=clock,
    )
    first = store.mint_session(scope=CapabilityScope(
        instance_id="instance-1",
        connection_id="connection-1",
        surface="macos",
        view_id="main",
    ))

    second = store.renew_session(first.token)

    assert second.scope == first.scope
    for token in (first.token, second.token):
        assert store.authenticate_session(token, scope=first.scope)
        for wrong_scope in (
            CapabilityScope("instance-2", "connection-1", "macos", "main"),
            CapabilityScope("instance-1", "connection-2", "macos", "main"),
            CapabilityScope("instance-1", "connection-1", "web", "main"),
            CapabilityScope("instance-1", "connection-1", "macos", "admin"),
        ):
            assert not store.authenticate_session(token, scope=wrong_scope)


def test_renewal_overlap_retires_previous_and_refuses_invalid_tokens(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    store = BootstrapSecretStore(
        tmp_path,
        capability_ttl=timedelta(seconds=30),
        capability_max_age=timedelta(seconds=90),
        now=clock,
    )
    first = store.mint_session(scope=_SCOPE)
    second = store.renew_session(first.token)
    store.revoke_session(first.token)

    assert not _authenticated(store, first.token)
    assert _authenticated(store, second.token)
    assert not _authenticated(store, "unauthenticated-token")

    third = store.renew_session(second.token)
    clock.now += timedelta(seconds=5)

    assert not _authenticated(store, second.token)
    assert _authenticated(store, third.token)

    clock.now = third.expires_at
    assert not _authenticated(store, third.token)


def test_renewal_overlap_keeps_only_current_and_immediate_predecessor(
    tmp_path: Path,
) -> None:
    store = BootstrapSecretStore(
        tmp_path,
        capability_ttl=timedelta(seconds=30),
        capability_max_age=timedelta(seconds=90),
    )
    first = store.mint_session(scope=_SCOPE)
    second = store.renew_session(first.token)

    third = store.renew_session(second.token)

    assert not _authenticated(store, first.token)
    assert _authenticated(store, second.token)
    assert _authenticated(store, third.token)
    assert store.active_session_count() == 2
