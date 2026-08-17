"""One-shot loopback bootstrap and in-memory native session capabilities."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast, final

from birkin import store
from birkin.native.protocol import NativeProtocolError

Clock = Callable[[], datetime]
_DEFAULT_BOOTSTRAP_TTL = timedelta(minutes=2)
_DEFAULT_CAPABILITY_TTL = timedelta(minutes=15)
_DEFAULT_CAPABILITY_MAX_AGE = timedelta(hours=8)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@final
@dataclass(frozen=True, slots=True)
class BootstrapRecord:
    secret: str
    expires_at: datetime


@final
@dataclass(frozen=True, slots=True)
class SessionCapability:
    token: str
    expires_at: datetime
    hard_expires_at: datetime


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
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)

    def issue(self) -> BootstrapRecord:
        with store.file_lock(self.lock_path):
            record = self._new_bootstrap()
            self._write_record(record)
            return record

    def current(self) -> BootstrapRecord:
        with store.file_lock(self.lock_path):
            return self._read_record()

    def exchange(self, secret: str) -> SessionCapability:
        with store.file_lock(self.lock_path):
            record = self._read_record()
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
            capability = self.mint_session()
            self._write_record(self._new_bootstrap())
            return capability

    def mint_session(self) -> SessionCapability:
        now = self._now()
        hard_expires_at = now + self._capability_max_age
        capability = SessionCapability(
            token=secrets.token_urlsafe(32),
            expires_at=min(now + self._capability_ttl, hard_expires_at),
            hard_expires_at=hard_expires_at,
        )
        with self._capability_lock:
            self._capabilities[capability.token] = capability
        return capability

    def authenticate_session(self, token: str) -> bool:
        with self._capability_lock:
            self._purge_expired()
            return self._find_token(token) is not None

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

    def _renew_known(self, known: str) -> SessionCapability:
        current = self._capabilities.pop(known)
        now = self._now()
        renewed = SessionCapability(
            token=secrets.token_urlsafe(32),
            expires_at=min(now + self._capability_ttl, current.hard_expires_at),
            hard_expires_at=current.hard_expires_at,
        )
        self._capabilities[renewed.token] = renewed
        return renewed

    def _new_bootstrap(self) -> BootstrapRecord:
        return BootstrapRecord(
            secret=secrets.token_urlsafe(32),
            expires_at=self._now() + self._ttl,
        )

    def _read_record(self) -> BootstrapRecord:
        try:
            raw = cast(object, json.loads(self.endpoint_path.read_text("utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            raise NativeProtocolError(
                "E_BOOTSTRAP_INVALID",
                "loopback bootstrap record is unavailable",
            ) from exc
        if not isinstance(raw, dict):
            raise NativeProtocolError(
                "E_BOOTSTRAP_INVALID",
                "loopback bootstrap record is malformed",
            )
        mapping = cast(dict[object, object], raw)
        secret = mapping.get("bootstrap_secret")
        expires_at = mapping.get("expires_at")
        if not isinstance(secret, str) or not isinstance(expires_at, str):
            raise NativeProtocolError(
                "E_BOOTSTRAP_INVALID",
                "loopback bootstrap record is malformed",
            )
        try:
            expiry = datetime.fromisoformat(expires_at)
        except ValueError as exc:
            raise NativeProtocolError(
                "E_BOOTSTRAP_INVALID",
                "loopback bootstrap record has an invalid expiry",
            ) from exc
        if expiry.tzinfo is None:
            raise NativeProtocolError(
                "E_BOOTSTRAP_INVALID",
                "loopback bootstrap expiry must be timezone-aware",
            )
        return BootstrapRecord(secret=secret, expires_at=expiry)

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

    def _write_record(self, record: BootstrapRecord) -> None:
        payload = {
            "transport": "loopback",
            "bootstrap_secret": record.secret,
            "expires_at": record.expires_at.isoformat(),
        }
        descriptor, temporary = tempfile.mkstemp(
            dir=self.root,
            prefix=".endpoint-",
            suffix=".json",
        )
        temporary_path = Path(temporary)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.endpoint_path)
            os.chmod(self.endpoint_path, 0o600)
        finally:
            temporary_path.unlink(missing_ok=True)
