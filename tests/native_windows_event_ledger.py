from __future__ import annotations

import json
import threading
from typing import final

from birkin.native.protocol import NativeEnvelope

MAX_LEDGER_EVENTS = 4096
MAX_LEDGER_BYTES = 4 * 1024 * 1024
MAX_SENTINEL_BYTES = 2 * 1024 * 1024


@final
class BoundedEventLedger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[NativeEnvelope] = []
        self._bytes = 0
        self._cursor = 0

    @property
    def cursor(self) -> int:
        with self._lock:
            return self._cursor

    def reset(self, cursor: int) -> None:
        with self._lock:
            self._events.clear()
            self._bytes = 0
            self._cursor = cursor

    def record(self, event: NativeEnvelope) -> None:
        cursor = event.body.get("cursor")
        assert isinstance(cursor, int) and not isinstance(cursor, bool)
        encoded_size = len(json.dumps(event.body, ensure_ascii=False).encode())
        with self._lock:
            assert cursor == self._cursor + 1, (
                f"non-contiguous event cursor: expected {self._cursor + 1}, got {cursor}"
            )
            next_count = len(self._events) + 1
            next_bytes = self._bytes + encoded_size
            assert next_count <= MAX_LEDGER_EVENTS, (
                f"event ledger count overflow: {next_count}>{MAX_LEDGER_EVENTS}"
            )
            assert next_bytes <= MAX_LEDGER_BYTES, (
                f"event ledger byte overflow: {next_bytes}>{MAX_LEDGER_BYTES}"
            )
            self._events.append(event)
            self._bytes = next_bytes
            self._cursor = cursor

    def summaries(self) -> tuple[str, ...]:
        with self._lock:
            events = tuple(self._events)
        rows: list[str] = []
        for event in events:
            payload = event.body.get("payload")
            data = payload.get("data") if isinstance(payload, dict) else None
            rows.append(";".join((
                f"cursor={event.body.get('cursor')}",
                f"type={event.body.get('type')}",
                f"command={event.body.get('command_id')}",
                f"data={str(data)[:160]!r}",
            )))
        return tuple(rows)

    def output_events_after(
        self,
        after_cursor: int,
        terminal_id: str,
    ) -> tuple[tuple[NativeEnvelope, str], ...]:
        with self._lock:
            events = tuple(self._events)
        output: list[tuple[NativeEnvelope, str]] = []
        total = 0
        for event in events:
            cursor = event.body.get("cursor")
            payload = event.body.get("payload")
            if (
                isinstance(cursor, int) and not isinstance(cursor, bool)
                and cursor > after_cursor
                and event.body.get("type") == "terminal.output"
                and isinstance(payload, dict)
                and payload.get("terminal_id") == terminal_id
            ):
                data = str(payload.get("data"))
                total += len(data.encode())
                assert total <= MAX_SENTINEL_BYTES, (
                    f"sentinel buffer overflow: {total}>{MAX_SENTINEL_BYTES}"
                )
                output.append((event, data))
        return tuple(output)

    def output_after(
        self,
        after_cursor: int,
        terminal_id: str,
        marker: str,
    ) -> NativeEnvelope | None:
        with self._lock:
            events = tuple(self._events)
        combined = bytearray()
        latest: NativeEnvelope | None = None
        for event in events:
            cursor = event.body.get("cursor")
            payload = event.body.get("payload")
            if (
                isinstance(cursor, int)
                and not isinstance(cursor, bool)
                and cursor > after_cursor
                and event.body.get("type") == "terminal.output"
                and isinstance(payload, dict)
                and payload.get("terminal_id") == terminal_id
            ):
                combined.extend(str(payload.get("data")).encode())
                assert len(combined) <= MAX_SENTINEL_BYTES, (
                    f"sentinel buffer overflow: {len(combined)}>{MAX_SENTINEL_BYTES}"
                )
                latest = event
                if marker.encode() in combined:
                    return latest
        return None
