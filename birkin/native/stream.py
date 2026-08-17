"""Bounded native event buffering with explicit desynchronization."""

from __future__ import annotations

import threading
from collections import deque
from typing import final


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

    def drain(self) -> tuple[dict[str, object], ...]:
        with self._lock:
            if self._marker_pending:
                self._marker_pending = False
                return (
                    {
                        "kind": "stream.desynchronized",
                        "body": {
                            "resume_after": self._last_delivered_cursor,
                        },
                    },
                )
            if self._desynchronized or not self._events:
                return ()
            events = tuple(self._events)
            self._events.clear()
            for event in events:
                cursor = event.get("cursor")
                if isinstance(cursor, int) and not isinstance(cursor, bool):
                    self._last_delivered_cursor = max(
                        self._last_delivered_cursor,
                        cursor,
                    )
            return events

    def resubscribe(self, *, after_cursor: int) -> None:
        if isinstance(after_cursor, bool) or after_cursor < 0:
            raise ValueError("after_cursor must be a non-negative integer")
        with self._lock:
            self._events.clear()
            self._last_delivered_cursor = after_cursor
            self._desynchronized = False
            self._marker_pending = False
