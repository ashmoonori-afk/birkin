from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from types import ModuleType
from typing import Protocol, cast

import pytest

from birkin.browser_aside_store import (
    BrowserFrameStore,
    FrameBlob,
    FrameStoreError,
)


class _Scheduler(Protocol):
    def demand(self, subscriber_id: str) -> None: ...

    def dirty(self) -> None: ...

    def next_capture(self) -> int | None: ...

    def complete(self, sequence: int) -> None: ...

    def snapshot(self) -> dict[str, int]: ...


class _FrameModule(Protocol):
    def browser_frame_scheduler(
        self,
        *,
        clock: Callable[[], float],
        min_interval: float,
    ) -> _Scheduler: ...

    def frame_context_record(
        self,
        blob: FrameBlob,
        *,
        generation: int,
        frame_revision: int,
    ) -> dict[str, object]: ...


def _module() -> _FrameModule:
    module: ModuleType = importlib.import_module(
        "birkin.browser_aside_frames"
    )
    return cast(_FrameModule, cast(object, module))


class _LeasedStore(Protocol):
    def publish(self, content: bytes) -> tuple[FrameBlob, bool]: ...

    def lease(self, ref: str) -> AbstractContextManager[FrameBlob]: ...

    def stats(self) -> dict[str, int]: ...


def test_frame_backpressure_coalesces_dirty_bursts() -> None:
    now = [1.0]
    scheduler = _module().browser_frame_scheduler(
        clock=lambda: now[0],
        min_interval=0.1,
    )
    scheduler.demand("web-1")
    for _ in range(10_000):
        scheduler.dirty()
    first = scheduler.next_capture()
    assert first == 10_000
    assert scheduler.next_capture() is None
    for _ in range(10_000):
        scheduler.dirty()
    assert scheduler.snapshot() == {
        "capture_in_flight": 1,
        "pending_dirty": 1,
        "subscriber_count": 1,
    }
    scheduler.complete(first)
    now[0] = 1.1
    assert scheduler.next_capture() == 20_000


def test_frame_cas_quota_respects_reader_leases_and_eviction() -> None:
    store = cast(
        _LeasedStore,
        cast(
            object,
            BrowserFrameStore(max_frame_bytes=4, max_store_bytes=8),
        ),
    )
    first, _ = store.publish(b"aaaa")
    with store.lease(first.ref):
        second, _ = store.publish(b"bbbb")
        assert second.ref != first.ref
        with pytest.raises(FrameStoreError):
            _ = store.publish(b"cccc")
        assert store.stats() == {
            "blob_count": 2,
            "leased_count": 1,
            "bytes": 8,
        }
    third, _ = store.publish(b"cccc")
    assert third.ref != second.ref
    assert store.stats()["bytes"] <= 8


def test_frame_context_contains_digest_ref_but_never_binary() -> None:
    store = BrowserFrameStore(max_frame_bytes=64, max_store_bytes=64)
    blob, _ = store.publish(b"\xff\xd8\xff\xe0JFIF-private")
    record = _module().frame_context_record(
        blob,
        generation=2,
        frame_revision=7,
    )
    assert set(record) == {
        "generation",
        "frame_revision",
        "frame_digest",
        "frame_ref",
    }
    encoded = json.dumps(record)
    assert "JFIF" not in encoded
    assert "base64" not in encoded
    assert "content" not in encoded
