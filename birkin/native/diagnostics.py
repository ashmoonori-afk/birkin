"""Bounded in-memory diagnostics safe for user export."""

from __future__ import annotations

import json
import os
import threading
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import final

from birkin.native.private_storage import create_private_temp
from birkin.native.projection import public_error_text

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@final
class DiagnosticRing:
    """Thread-safe bounded diagnostic history with no authority state."""

    def __init__(
        self,
        *,
        capacity: int = 200,
        now: Clock = _utc_now,
    ) -> None:
        if isinstance(capacity, bool) or capacity <= 0:
            raise ValueError("capacity must be a positive integer")
        self._entries: deque[dict[str, object]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._now = now

    def record(
        self,
        *,
        transport: str,
        state: str,
        error_code: str,
        attempt: int,
        last_cursor: int,
        instance_id: str,
        server_version: str,
        client_version: str,
        detail: str,
    ) -> None:
        entry: dict[str, object] = {
            "timestamp": self._now().isoformat(),
            "transport": transport,
            "state": state,
            "error_code": error_code,
            "attempt": attempt,
            "last_cursor": last_cursor,
            "instance_id": instance_id,
            "server_version": server_version,
            "client_version": client_version,
            "detail": public_error_text(detail),
        }
        with self._lock:
            self._entries.append(entry)

    def entries(self) -> list[dict[str, object]]:
        with self._lock:
            return [dict(entry) for entry in self._entries]

    def to_json(self) -> str:
        return json.dumps(
            self.entries(),
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

    def export(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = create_private_temp(
            destination.parent,
            prefix=f".{destination.name}-",
        )
        temporary_path = Path(temporary)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                _ = handle.write(self.to_json())
                _ = handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
