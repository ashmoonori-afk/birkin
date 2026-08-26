from __future__ import annotations

import pytest

from birkin.native.protocol import NATIVE_PROTOCOL_NAME, NATIVE_PROTOCOL_VERSION, NativeEnvelope
from tests import native_windows_event_ledger as ledger_module
from tests.native_windows_event_ledger import BoundedEventLedger


def _event(cursor: int, data: str) -> NativeEnvelope:
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


def test_ledger_resets_cursor_and_finds_sentinel_across_chunks() -> None:
    ledger = BoundedEventLedger()
    ledger.reset(40)
    ledger.record(_event(41, "BOUND"))
    ledger.record(_event(42, "ARY"))
    assert ledger.output_after(40, "terminal-1", "BOUNDARY") == _event(42, "ARY")
    ledger.reset(100)
    assert ledger.cursor == 100
    assert ledger.output_after(40, "terminal-1", "BOUNDARY") is None
    ledger.record(_event(101, "NEW"))
    assert ledger.cursor == 101


def test_masked_completion_barrier_does_not_require_full_prompt() -> None:
    ledger = BoundedEventLedger()
    ledger.reset(8)
    ledger.record(_event(9, "set PASSWORD=[REDACTED]\\r\\nC:\\partial"))
    completed = NativeEnvelope(
        NATIVE_PROTOCOL_NAME,
        NATIVE_PROTOCOL_VERSION,
        "event",
        "event-10",
        None,
        {"cursor": 10, "type": "command.completed", "command_id": "assign"},
    )
    ledger.record(completed)
    assert ledger.output_after(8, "terminal-1", "[REDACTED]") == _event(
        9, "set PASSWORD=[REDACTED]\\r\\nC:\\partial"
    )
    assert ledger.cursor >= 10


def test_ledger_fails_diagnostically_at_count_and_byte_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = BoundedEventLedger()
    monkeypatch.setattr(ledger_module, "MAX_LEDGER_EVENTS", 1)
    ledger.record(_event(1, "one"))
    with pytest.raises(AssertionError, match="count overflow"):
        ledger.record(_event(2, "two"))
    ledger.reset(0)
    monkeypatch.setattr(ledger_module, "MAX_LEDGER_EVENTS", 4096)
    monkeypatch.setattr(ledger_module, "MAX_LEDGER_BYTES", 1)
    with pytest.raises(AssertionError, match="byte overflow"):
        ledger.record(_event(1, "large"))
