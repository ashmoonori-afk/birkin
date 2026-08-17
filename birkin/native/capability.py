"""One-shot loopback bootstrap and in-memory native session capabilities."""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import final

from birkin import store
from birkin.native.bootstrap import (
    BootstrapRecord,
    new_record,
    prepare_private_root,
    read_record,
    write_record,
)
from birkin.native.protocol import NativeProtocolError

Clock = Callable[[], datetime]
_DEFAULT_BOOTSTRAP_TTL = timedelta(minutes=2)
_DEFAULT_CAPABILITY_TTL = timedelta(minutes=15)
_DEFAULT_CAPABILITY_MAX_AGE = timedelta(hours=8)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@final
@dataclass(frozen=True, slots=True)
class CapabilityScope:
    instance_id: str
    connection_id: str
    surface: str
    view_id: str


@final
@dataclass(frozen=True, slots=True)
class SessionCapability:
    token: str
    expires_at: datetime
    hard_expires_at: datetime
    scope: CapabilityScope


@final
class BootstrapSecretStore:
    """Private disk bootstrap exchanged once for a memory-only capability."""

    def __init__(
        self,
        root: Path,
        *,
        ttl: timedelta = _DEFAULT_BOOTSTRAP_TTL,
        capability_ttl: timedelta = _DEFAULT_CAPABILITY_TTL,
        capability_max_age: timedelta = _DEFAULT_CAPABILITY_MAX_AGE,
        now: Clock = _utc_now,
    ) -> None:
        if (
            ttl <= timedelta(0)
            or capability_ttl <= timedelta(0)
            or capability_max_age < capability_ttl
        ):
            raise ValueError("capability lifetimes must be positive")
        self.root = root
        self.endpoint_path = root / "endpoint.json"
        self.lock_path = root / "bootstrap.lock"
        self._ttl = ttl
        self._capability_ttl = capability_ttl
        self._capability_max_age = capability_max_age
        self._now = now
        self._capabilities: dict[str, SessionCapability] = {}
        self._capability_lock = threading.Lock()
        prepare_private_root(self.root)

    def issue(self) -> BootstrapRecord:
        with store.file_lock(self.lock_path):
            record = new_record(self._now(), self._ttl)
            write_record(self.endpoint_path, record)
            return record

    def current(self) -> BootstrapRecord:
        with store.file_lock(self.lock_path):
            return read_record(self.endpoint_path)

    def exchange(
        self,
        secret: str,
        *,
        scope: CapabilityScope,
    ) -> SessionCapability:
        with store.file_lock(self.lock_path):
            record = read_record(self.endpoint_path)
            if self._now() >= record.expires_at:
                raise NativeProtocolError(
                    "E_BOOTSTRAP_EXPIRED",
                    "loopback bootstrap secret expired",
                )
            if not secrets.compare_digest(secret, record.secret):
                raise NativeProtocolError(
                    "E_BOOTSTRAP_INVALID",
                    "loopback bootstrap secret is invalid",
                )
            capability = self.mint_session(scope=scope)
            write_record(
                self.endpoint_path,
                new_record(self._now(), self._ttl),
            )
            return capability

    def mint_session(self, *, scope: CapabilityScope) -> SessionCapability:
        now = self._now()
        hard_expires_at = now + self._capability_max_age
        capability = SessionCapability(
            token=secrets.token_urlsafe(32),
            expires_at=min(now + self._capability_ttl, hard_expires_at),
            hard_expires_at=hard_expires_at,
            scope=scope,
        )
        with self._capability_lock:
            self._capabilities[capability.token] = capability
        return capability

    def authenticate_session(
        self,
        token: str,
        *,
        scope: CapabilityScope,
    ) -> bool:
        with self._capability_lock:
            self._purge_expired()
            known = self._find_token(token)
            return (
                known is not None
                and self._capabilities[known].scope == scope
            )

    def renew_session(self, token: str) -> SessionCapability:
        with self._capability_lock:
            self._purge_expired()
            known = self._find_token(token)
            if known is None:
                raise NativeProtocolError(
                    "E_CAPABILITY_EXPIRED",
                    "native session capability expired or is invalid",
                )
            return self._renew_known(known)

    def renew_if_due(self, token: str) -> SessionCapability | None:
        with self._capability_lock:
            self._purge_expired()
            known = self._find_token(token)
            if known is None:
                raise NativeProtocolError(
                    "E_CAPABILITY_EXPIRED",
                    "native session capability expired or is invalid",
                )
            capability = self._capabilities[known]
            if capability.expires_at - self._now() > self._capability_ttl / 3:
                return None
            return self._renew_known(known)

    def revoke_session(self, token: str) -> None:
        with self._capability_lock:
            known = self._find_token(token)
            if known is not None:
                del self._capabilities[known]

    def revoke_all_sessions(self) -> None:
        with self._capability_lock:
            self._capabilities.clear()

    def active_session_count(self) -> int:
        with self._capability_lock:
            self._purge_expired()
            return len(self._capabilities)

    def _renew_known(self, known: str) -> SessionCapability:
        current = self._capabilities.pop(known)
        now = self._now()
        renewed = SessionCapability(
            token=secrets.token_urlsafe(32),
            expires_at=min(now + self._capability_ttl, current.hard_expires_at),
            hard_expires_at=current.hard_expires_at,
            scope=current.scope,
        )
        self._capabilities[renewed.token] = renewed
        return renewed

    def _purge_expired(self) -> None:
        now = self._now()
        expired = [
            token
            for token, capability in self._capabilities.items()
            if now >= capability.expires_at
            or now >= capability.hard_expires_at
        ]
        for token in expired:
            del self._capabilities[token]

    def _find_token(self, token: str) -> str | None:
        return next(
            (
                known
                for known in self._capabilities
                if secrets.compare_digest(token, known)
            ),
            None,
        )
