"""Bounded cooperative cancellation tombstones."""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock


class CancellationRegistry:
    def __init__(self, *, max_entries: int = 1024):
        self.max_entries = max_entries
        self._cancelled: OrderedDict[str, None] = OrderedDict()
        self._lock = Lock()

    def cancel(self, action_id: str) -> bool:
        with self._lock:
            if (
                action_id not in self._cancelled
                and len(self._cancelled) >= self.max_entries
            ):
                return False
            self._cancelled[action_id] = None
            self._cancelled.move_to_end(action_id)
            return True

    def is_cancelled(self, action_id: str) -> bool:
        with self._lock:
            return action_id in self._cancelled
