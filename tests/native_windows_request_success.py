from __future__ import annotations

from typing import Protocol

from birkin.native.protocol import NativeEnvelope
from tests.native_windows_event_ledger import BoundedEventLedger


class RequestHarness(Protocol):
    ledger: BoundedEventLedger

    @property
    def current_cursor(self) -> int: ...

    def request(
        self,
        command_type: str,
        command_id: str,
        payload: dict[str, object],
        *,
        expected_cursor: int | None = None,
    ) -> tuple[NativeEnvelope, list[NativeEnvelope]]: ...


def request_success(
    harness: RequestHarness,
    command_type: str,
    command_id: str,
    payload: dict[str, object],
) -> tuple[NativeEnvelope, list[NativeEnvelope]]:
    submitted_cursor = harness.current_cursor
    sequence = payload.get("sequence")
    response, events = harness.request(command_type, command_id, payload)
    if response.kind != "receipt":
        code = response.body.get("code")
        message = response.body.get("message")
        diagnostic = ";".join((
            f"unexpected pre-accept response: code={code}",
            f"message={message}",
            f"submitted_expected_cursor={submitted_cursor}",
            f"current_cursor={harness.current_cursor}",
            f"input_sequence={sequence}",
            f"ledger={harness.ledger.summaries()}",
        ))
        raise AssertionError(diagnostic)
    return response, events
