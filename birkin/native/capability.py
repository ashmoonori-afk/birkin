"""One-shot loopback bootstrap and in-memory native session capabilities."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
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


@final
class BootstrapSecretStore:
    """Private disk bootstrap exchanged once for a memory-only capability."""

    def __init__(
        self,
        root: Path,
        *,
        ttl: timedelta = _DEFAULT_BOOTSTRAP_TTL,
        capability_ttl: timedelta = _DEFAULT_CAPABILITY_TTL,
        now: Clock = _utc_now,
    ) -> None:
        if ttl <= timedelta(0) or capability_ttl <= timedelta(0):
            raise ValueError("capability lifetimes must be positive")
        self.root = root
        self.endpoint_path = root / "endpoint.json"
        self.lock_path = root / "bootstrap.lock"
        self._ttl = ttl
        self._capability_ttl = capability_ttl
        self._now = now
        self._capabilities: dict[str, datetime] = {}
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
            capability = SessionCapability(
                token=secrets.token_urlsafe(32),
                expires_at=self._now() + self._capability_ttl,
            )
            self._capabilities[capability.token] = capability.expires_at
            self._write_record(self._new_bootstrap())
            return capability

    def authenticate_session(self, token: str) -> bool:
        now = self._now()
        expired = [
            known
            for known, expires_at in self._capabilities.items()
            if now >= expires_at
        ]
        for known in expired:
            del self._capabilities[known]
        return any(
            secrets.compare_digest(token, known)
            for known in self._capabilities
        )

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
