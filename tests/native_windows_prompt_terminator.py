from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol, cast

from birkin.native.protocol import NativeEnvelope
from tests.native_windows_event_ledger import BoundedEventLedger


class PromptHarness(Protocol):
    ledger: BoundedEventLedger


def await_prompt_terminator(
    harness: PromptHarness,
    terminal_id: str,
    sentinel: str,
    *,
    after_cursor: int,
    timeout: float,
) -> NativeEnvelope:
    deadline = time.monotonic() + timeout
    reader = cast(object, getattr(harness, "read_next", None))
    if not callable(reader):
        reader = cast(object, getattr(harness, "_read"))
    read_next = cast(Callable[[float], NativeEnvelope], reader)
    while True:
        combined = ""
        for event, data in harness.ledger.output_events_after(
            after_cursor, terminal_id
        ):
            combined += data
            sentinel_index = combined.find(sentinel)
            if sentinel_index >= 0 and ">" in combined[sentinel_index + len(sentinel):]:
                return event
        if time.monotonic() >= deadline:
            raise TimeoutError("prompt terminator deadline expired")
        _ = read_next(deadline)
