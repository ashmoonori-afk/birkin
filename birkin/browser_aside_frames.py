"""Bounded frame scheduling and digest-only context records."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import final

from birkin.browser_aside_store import FrameBlob


@final
class BrowserFrameScheduler:
    def __init__(
        self,
        *,
        clock: Callable[[], float],
        min_interval: float,
    ) -> None:
        if min_interval < 0:
            raise ValueError("frame interval must be non-negative")
        self._clock = clock
        self._min_interval = min_interval
        self._subscribers: set[str] = set()
        self._dirty_sequence = 0
        self._captured_sequence = 0
        self._capture_in_flight: int | None = None
        self._last_capture = float("-inf")
        self._lock = RLock()

    def demand(self, subscriber_id: str) -> None:
        if not subscriber_id:
            raise ValueError("subscriber id must not be empty")
        with self._lock:
            self._subscribers.add(subscriber_id)

    def dirty(self) -> None:
        with self._lock:
            self._dirty_sequence += 1

    def next_capture(self) -> int | None:
        with self._lock:
            if (
                not self._subscribers
                or self._capture_in_flight is not None
                or self._dirty_sequence <= self._captured_sequence
                or self._clock() - self._last_capture
                < self._min_interval
            ):
                return None
            self._capture_in_flight = self._dirty_sequence
            return self._capture_in_flight

    def complete(self, sequence: int) -> None:
        with self._lock:
            if self._capture_in_flight != sequence:
                raise ValueError("frame capture sequence is stale")
            self._captured_sequence = sequence
            self._capture_in_flight = None
            self._last_capture = self._clock()

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "capture_in_flight": int(
                    self._capture_in_flight is not None
                ),
                "pending_dirty": int(
                    self._dirty_sequence
                    > (
                        self._capture_in_flight
                        or self._captured_sequence
                    )
                ),
                "subscriber_count": len(self._subscribers),
            }


def browser_frame_scheduler(
    *,
    clock: Callable[[], float],
    min_interval: float,
) -> BrowserFrameScheduler:
    return BrowserFrameScheduler(
        clock=clock,
        min_interval=min_interval,
    )


def frame_context_record(
    blob: FrameBlob,
    *,
    generation: int,
    frame_revision: int,
) -> dict[str, object]:
    return {
        "generation": generation,
        "frame_revision": frame_revision,
        "frame_digest": blob.digest,
        "frame_ref": blob.ref,
    }
