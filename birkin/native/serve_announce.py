"""Announcement sink for the native bridge process.

Serving keeps its control flow in :mod:`birkin.native.serve`; the one-line JSON
records it announces are written here so that module stays inside the native
small-module gate.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TypeAlias

Announce: TypeAlias = Callable[[str], None]


def emit(announce: Announce, record: dict[str, object]) -> None:
    """Announce one record as a single compact JSON line."""
    announce(json.dumps(record, separators=(",", ":")))


def write_line(line: str) -> None:
    """Default announce sink: one flushed line on stdout."""
    print(line, flush=True)


def connection_failure(exc: BaseException) -> dict[str, object]:
    """Describe a per-connection failure, keeping the exception's own message."""
    return {
        "event": "connection_failed",
        "error": f"{type(exc).__name__}: {exc}"[:200],
    }
