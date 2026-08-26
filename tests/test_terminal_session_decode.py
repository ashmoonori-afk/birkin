from __future__ import annotations

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
    """Mutable fake that exposes one UTF-8 scalar across two refresh calls."""

    def __init__(self) -> None:
        self.pid = 731
        encoded = "한".encode("utf-8")
        self._reads = [encoded[:1], b"", encoded[1:], b""]

    def poll(self) -> int | None:
        return None

    def read(self, max_bytes: int, timeout: float) -> bytes:
        _ = max_bytes, timeout
        return self._reads.pop(0) if self._reads else b""

    def write(self, data: bytes, timeout: float) -> None:
        _ = data, timeout

    def resize(self, columns: int, rows: int) -> None:
        _ = columns, rows

    def signal(self, name: str) -> None:
        _ = name

    def close(self, exit_code: int = 1) -> None:
        _ = exit_code


def test_output_preserves_utf8_scalar_when_reads_span_refresh_calls(
    tmp_path: Path,
) -> None:
    # Given: process output splits one UTF-8 scalar across create and input refreshes.
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

    # When: the second refresh receives the remainder of that scalar.
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

    # Then: output contains the exact scalar, never replacement characters.
    assert result["output"] == "한"
    assert "�" not in str(events)
