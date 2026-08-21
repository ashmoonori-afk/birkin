"""Bounded native event buffering with explicit desynchronization."""

from __future__ import annotations

import threading
from collections import deque
from typing import final


def _event_cursor(event: dict[str, object]) -> int | None:
    cursor = event.get("cursor")
    if isinstance(cursor, bool) or not isinstance(cursor, int):
        return None
    return cursor


@final
class BoundedEventBuffer:
    """Never silently drops projection events under backpressure."""

    def __init__(self, *, capacity: int = 512) -> None:
        if isinstance(capacity, bool) or capacity <= 0:
            raise ValueError("capacity must be a positive integer")
        self._capacity = capacity
        self._events: deque[dict[str, object]] = deque()
        self._last_delivered_cursor = 0
        self._desynchronized = False
        self._marker_pending = False
        self._lock = threading.Lock()

    def push(self, event: dict[str, object]) -> bool:
        with self._lock:
            if self._desynchronized:
                return False
            if len(self._events) >= self._capacity:
                self._events.clear()
                self._desynchronized = True
                self._marker_pending = True
                return False
            self._events.append(dict(event))
            return True

    def mark_delivered(self, *, cursor: int) -> None:
        """Record a cursor already delivered outside this buffer.

        Subscription replay writes canonical events straight to the socket, so
        the buffer must forget anything the replay already covered instead of
        sending it a second time.
        """
        if isinstance(cursor, bool) or cursor < 0:
            raise ValueError("cursor must be a non-negative integer")
        with self._lock:
            self._last_delivered_cursor = max(self._last_delivered_cursor, cursor)
            while self._events:
                buffered = _event_cursor(self._events[0])
                if buffered is None or buffered > self._last_delivered_cursor:
                    break
                _ = self._events.popleft()

    def drain(self) -> tuple[dict[str, object], ...]:
        with self._lock:
            if self._marker_pending:
                self._marker_pending = False
                return (self._desynchronized_notice(),)
            if self._desynchronized or not self._events:
                return ()
            delivered: list[dict[str, object]] = []
            while self._events:
                cursor = _event_cursor(self._events[0])
                if cursor is None:
                    delivered.append(self._events.popleft())
                    continue
                if cursor <= self._last_delivered_cursor:
                    _ = self._events.popleft()
                    continue
                if cursor != self._last_delivered_cursor + 1:
                    self._events.clear()
                    self._desynchronized = True
                    self._marker_pending = True
                    break
                delivered.append(self._events.popleft())
                self._last_delivered_cursor = cursor
            if not delivered and self._marker_pending:
                self._marker_pending = False
                return (self._desynchronized_notice(),)
            return tuple(delivered)

    def _desynchronized_notice(self) -> dict[str, object]:
        return {
            "kind": "stream.desynchronized",
            "body": {"resume_after": self._last_delivered_cursor},
        }

    def has_pending(self) -> bool:
        with self._lock:
            return self._marker_pending or bool(self._events)

    def resubscribe(self, *, after_cursor: int) -> None:
        if isinstance(after_cursor, bool) or after_cursor < 0:
            raise ValueError("after_cursor must be a non-negative integer")
        with self._lock:
            self._events.clear()
            self._last_delivered_cursor = after_cursor
            self._desynchronized = False
            self._marker_pending = False


@final
class NativeEventQueue:
    """Wakeable bounded queue used by one connection writer."""

    def __init__(self, *, capacity: int = 512) -> None:
        self._buffer = BoundedEventBuffer(capacity=capacity)
        self._condition = threading.Condition()
        self._closed = False

    def publish(self, event: dict[str, object]) -> None:
        _ = self._buffer.push(event)
        with self._condition:
            self._condition.notify_all()

    def wait_for_pending(self, *, timeout: float) -> None:
        with self._condition:
            if not self._closed and not self._buffer.has_pending():
                _ = self._condition.wait(timeout)

    def drain(self) -> tuple[dict[str, object], ...]:
        return self._buffer.drain()

    def resubscribe(self, *, after_cursor: int) -> None:
        self._buffer.resubscribe(after_cursor=after_cursor)

    def mark_delivered(self, *, cursor: int) -> None:
        self._buffer.mark_delivered(cursor=cursor)

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
