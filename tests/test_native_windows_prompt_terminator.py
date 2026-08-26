from __future__ import annotations

import time
from typing import final

import pytest

from birkin.native.protocol import NATIVE_PROTOCOL_NAME, NATIVE_PROTOCOL_VERSION, NativeEnvelope
from tests.native_windows_event_ledger import BoundedEventLedger
from tests.native_windows_prompt_terminator import await_prompt_terminator


def _output(cursor: int, data: str) -> NativeEnvelope:
    return NativeEnvelope(
        NATIVE_PROTOCOL_NAME,
        NATIVE_PROTOCOL_VERSION,
        "event",
        f"event-{cursor}",
        None,
        {
            "cursor": cursor,
            "type": "terminal.output",
            "payload": {"terminal_id": "terminal-1", "data": data},
        },
    )


@final
class FakeHarness:
    def __init__(self, frames: list[NativeEnvelope]) -> None:
        self.ledger = BoundedEventLedger()
        self.ledger.reset(40)
        self.frames = frames

    def read_next(self, deadline: float) -> NativeEnvelope:
        if time.monotonic() >= deadline or not self.frames:
            raise TimeoutError("prompt terminator deadline expired")
        frame = self.frames.pop(0)
        self.ledger.record(frame)
        return frame


def test_prompt_terminator_survives_raw_hard_wrap_without_cwd_claim() -> None:
    harness = FakeHarness([
        _output(41, "SENTINEL"),
        _output(42, "round\x1b[23;80Hd_trip0>"),
    ])
    event = await_prompt_terminator(
        harness, "terminal-1", "SENTINEL", after_cursor=40, timeout=1.0
    )
    assert event.body["cursor"] == 42


def test_prompt_terminator_missing_after_sentinel_uses_absolute_deadline() -> None:
    harness = FakeHarness([_output(41, "SENTINEL-without-prompt")])
    with pytest.raises(TimeoutError, match="deadline"):
        _ = await_prompt_terminator(
            harness, "terminal-1", "SENTINEL", after_cursor=40, timeout=0.1
        )
