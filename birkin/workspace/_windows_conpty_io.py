"""Private ConPTY input request state."""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(slots=True)
class WriteRequest:
    data: bytes
    done: threading.Event
    error: OSError | None = None
