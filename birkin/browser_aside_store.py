"""Bounded workspace-scoped content-addressed frame storage."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections import Counter, OrderedDict
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import final

MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_STORE_BYTES = 64 * 1024 * 1024


class FrameStoreError(RuntimeError):
    """A frame could not be admitted to the bounded store."""


@dataclass(frozen=True, slots=True)
class FrameBlob:
    digest: str
    ref: str
    content: bytes


@final
class BrowserFrameStore:
    """Latest-value CAS with workspace-private content addresses."""

    def __init__(
        self,
        *,
        max_frame_bytes: int = MAX_FRAME_BYTES,
        max_store_bytes: int = MAX_STORE_BYTES,
    ) -> None:
        if max_frame_bytes <= 0 or max_store_bytes < max_frame_bytes:
            raise ValueError("invalid frame store limits")
        self._max_frame_bytes = max_frame_bytes
        self._max_store_bytes = max_store_bytes
        self._key = secrets.token_bytes(32)
        self._lock = RLock()
        self._blobs: OrderedDict[str, FrameBlob] = OrderedDict()
        self._leases: Counter[str] = Counter()
        self._current_ref: str | None = None
        self._bytes = 0

    def publish(self, content: bytes) -> tuple[FrameBlob, bool]:
        digest, ref = self._content_address(content)
        with self._lock:
            return self._publish_locked(content, digest, ref)

    def publish_before(
        self,
        content: bytes,
        *,
        deadline: float,
        clock: Callable[[], float],
    ) -> tuple[FrameBlob, bool] | None:
        digest, ref = self._content_address(content)
        with self._lock:
            if clock() >= deadline:
                return None
            return self._publish_locked(content, digest, ref)

    def _content_address(self, content: bytes) -> tuple[str, str]:
        if not content or len(content) > self._max_frame_bytes:
            raise FrameStoreError("frame exceeds the encoded byte limit")
        digest_hex = hmac.new(
            self._key,
            content,
            hashlib.sha256,
        ).hexdigest()
        digest = f"hmac-sha256:{digest_hex}"
        ref = f"birkin-frame:v1:{digest_hex}"
        return digest, ref

    def _publish_locked(
        self,
        content: bytes,
        digest: str,
        ref: str,
    ) -> tuple[FrameBlob, bool]:
        existing = next(
            (
                blob
                for blob in self._blobs.values()
                if hmac.compare_digest(blob.digest, digest)
            ),
            None,
        )
        if existing is not None:
            if existing.content != content:
                raise FrameStoreError("frame digest collision")
            self._current_ref = existing.ref
            return existing, False
        if len(content) > self._max_store_bytes:
            raise FrameStoreError("frame store quota exceeded")
        self._evict_for(len(content))
        blob = FrameBlob(digest=digest, ref=ref, content=bytes(content))
        self._blobs[ref] = blob
        self._bytes += len(content)
        self._current_ref = ref
        return blob, True

    def current(self) -> FrameBlob | None:
        with self._lock:
            if self._current_ref is None:
                return None
            return self._blobs.get(self._current_ref)

    @contextmanager
    def lease(self, ref: str) -> Generator[FrameBlob]:
        with self._lock:
            blob = self._blobs.get(ref)
            if blob is None:
                raise KeyError(ref)
            self._leases[ref] += 1
        try:
            yield blob
        finally:
            with self._lock:
                self._leases[ref] -= 1
                if self._leases[ref] <= 0:
                    del self._leases[ref]

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "blob_count": len(self._blobs),
                "leased_count": sum(self._leases.values()),
                "bytes": self._bytes,
            }

    def clear(self) -> None:
        with self._lock:
            self._blobs.clear()
            self._leases.clear()
            self._current_ref = None
            self._bytes = 0
            self._key = secrets.token_bytes(32)

    def _evict_for(self, incoming: int) -> None:
        while self._bytes + incoming > self._max_store_bytes:
            candidate = next(
                (
                    ref
                    for ref in self._blobs
                    if ref != self._current_ref
                    and self._leases.get(ref, 0) == 0
                ),
                None,
            )
            if candidate is None:
                raise FrameStoreError("frame store quota exceeded")
            removed = self._blobs.pop(candidate)
            self._bytes -= len(removed.content)
