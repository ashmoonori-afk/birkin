from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ThreadDeadline:
    """Bound a threaded test with one deadline instead of per-step timing."""

    expires_at: float

    @classmethod
    def after(cls, seconds: float) -> ThreadDeadline:
        return cls(expires_at=time.monotonic() + seconds)

    @property
    def remaining(self) -> float:
        return max(0.0, self.expires_at - time.monotonic())

    def wait_for(self, event: threading.Event, description: str) -> None:
        assert event.wait(timeout=self.remaining), (
            f"test deadline expired before {description}"
        )

    def join(self, thread: threading.Thread, description: str) -> None:
        thread.join(timeout=self.remaining)
        assert not thread.is_alive(), f"test deadline expired before {description}"
