from __future__ import annotations

import threading
from pathlib import Path
from typing import final

from birkin.workspace.terminal_policy import (
    ApprovedTerminalLaunch,
    TerminalIdentity,
    TerminalInputIntent,
)
from birkin.workspace.terminal_session import TerminalSessions


@final
class SplitUtf8Process:
    """Event-backed fake that exposes one scalar across two blocking reads."""

    def __init__(self) -> None:
        self.pid = 731
        encoded = "한".encode("utf-8")
        self._first = encoded[:1]
        self._second = encoded[1:]
        self._second_ready = False
        self._closed = False
        self._condition = threading.Condition()

    def poll(self) -> int | None:
        with self._condition:
            return 0 if self._closed else None

    def read(self, max_bytes: int, timeout: float | None) -> bytes:
        with self._condition:
            if self._first:
                chunk, self._first = self._first[:max_bytes], self._first[max_bytes:]
                return chunk
            def ready() -> bool:
                return self._second_ready or self._closed

            if not ready() and not self._condition.wait_for(ready, timeout):
                return b""
            if self._closed:
                return b""
            chunk, self._second = self._second[:max_bytes], self._second[max_bytes:]
            self._second_ready = bool(self._second)
            return chunk

    def write(self, data: bytes, timeout: float) -> None:
        del data, timeout
        with self._condition:
            self._second_ready = True
            self._condition.notify_all()

    def resize(self, columns: int, rows: int) -> None:
        del columns, rows

    def signal(self, name: str) -> None:
        del name

    def close(self, exit_code: int = 1) -> None:
        del exit_code
        with self._condition:
            self._closed = True
            self._condition.notify_all()


def test_output_preserves_utf8_scalar_when_reads_span_refresh_calls(
    tmp_path: Path,
) -> None:
    # Given a process whose second chunk is event-blocked until terminal input
    process = SplitUtf8Process()
    events: list[tuple[str, dict[str, object]]] = []
    sessions = TerminalSessions(
        "session-1",
        lambda kind, payload: events.append((kind, payload)),
        lambda _shell, _cwd, _environment, _columns, _rows: process,
    )
    opened = sessions.create(
        ApprovedTerminalLaunch(tmp_path / "shell", tmp_path, {}, "approval-1")
    )
    try:
        # When input releases the exact second-chunk condition
        result = sessions.input(
            TerminalInputIntent(
                identity=TerminalIdentity(
                    terminal_id=str(opened["terminal_id"]),
                    lease=str(opened["lease"]),
                ),
                sequence=1,
                data=b"input",
            )
        )
        # Then the sole pump preserves the scalar and no replacement appears
        assert result["output"] == "한"
        assert "�" not in str(events)
    finally:
        sessions.close_all()
