"""Bounded content-addressed screenshot artifact storage."""

from __future__ import annotations

import hashlib
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import final


class ArtifactQuotaExceeded(RuntimeError):
    """Artifact count or byte quota would be exceeded."""


@dataclass(frozen=True, slots=True)
class BrowserArtifact:
    ref: str
    digest: str
    byte_length: int


@dataclass(frozen=True, slots=True)
class _ArtifactRecord:
    artifact: BrowserArtifact
    path: Path
    created_at: float


@final
class BrowserArtifactStore:
    def __init__(
        self,
        root: Path,
        *,
        clock: Callable[[], float],
        retention_seconds: int,
        max_records: int,
        max_bytes: int,
    ) -> None:
        if (
            retention_seconds <= 0
            or max_records <= 0
            or max_bytes <= 0
        ):
            raise ValueError("artifact limits must be positive")
        self._root = root.resolve()
        self._clock = clock
        self._retention = retention_seconds
        self._max_records = max_records
        self._max_bytes = max_bytes
        self._records: dict[str, _ArtifactRecord] = {}
        self._bytes = 0
        self._lock = RLock()
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._root.chmod(0o700)

    def put_screenshot(self, content: bytes) -> BrowserArtifact:
        if not content:
            raise ValueError("artifact content must not be empty")
        with self._lock:
            digest_hex = hashlib.sha256(content).hexdigest()
            digest = f"sha256:{digest_hex}"
            ref = f"birkin-artifact:v1:{digest_hex}"
            existing = self._records.get(ref)
            if existing is not None:
                if existing.path.read_bytes() != content:
                    raise RuntimeError("artifact digest collision")
                return existing.artifact
            if (
                len(self._records) >= self._max_records
                or self._bytes + len(content) > self._max_bytes
            ):
                raise ArtifactQuotaExceeded("artifact quota exceeded")
            path = self._root / digest_hex
            if path.exists():
                if path.read_bytes() != content:
                    raise RuntimeError("artifact digest collision")
            else:
                self._atomic_write(path, content)
            artifact = BrowserArtifact(ref, digest, len(content))
            self._records[ref] = _ArtifactRecord(
                artifact,
                path,
                self._clock(),
            )
            self._bytes += len(content)
            return artifact

    def resolve(self, ref: str) -> bytes:
        with self._lock:
            record = self._records.get(ref)
            if record is None:
                raise KeyError(ref)
            return record.path.read_bytes()

    def purge(self) -> tuple[str, ...]:
        cutoff = self._clock() - self._retention
        with self._lock:
            expired = tuple(
                ref
                for ref, record in self._records.items()
                if record.created_at < cutoff
            )
            for ref in expired:
                self._drop(ref)
            return expired

    def close(self) -> None:
        with self._lock:
            for ref in tuple(self._records):
                self._drop(ref)

    def _drop(self, ref: str) -> None:
        record = self._records.pop(ref)
        self._bytes -= record.artifact.byte_length
        if not any(
            other.path == record.path
            for other in self._records.values()
        ):
            record.path.unlink(missing_ok=True)

    def _atomic_write(self, path: Path, content: bytes) -> None:
        temporary = self._root / (
            f".{path.name}.{secrets.token_hex(6)}.tmp"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                _ = handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)
