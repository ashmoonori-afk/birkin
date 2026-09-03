"""A stuck writer is a connection failure, never an accept failure."""

from __future__ import annotations

import errno
import json
from pathlib import Path
from typing import final

from birkin.native.serve import BridgeProcess, NativeServeOptions


@final
class _StuckWriterEndpoint:
    """An endpoint whose teardown reports the writer that never stopped."""

    def __init__(self, failures: list[BaseException]) -> None:
        self._failures = failures

    def serve_once(self) -> None:
        if self._failures:
            raise self._failures.pop(0)

    def close(self) -> None:
        return None


def _process(tmp_path: Path, lines: list[str]) -> BridgeProcess:
    return BridgeProcess(
        NativeServeOptions.resolve(session_id="writer-timeout", root=tmp_path),
        lines.append,
    )


def test_writer_teardown_timeout_keeps_its_message_and_the_accept_budget(
    tmp_path: Path,
) -> None:
    """Given a connection whose writer never stopped, When the bridge absorbs
    the failure, Then the diagnostic keeps the writer's message and the accept
    budget the listener owns is left alone."""
    lines: list[str] = []
    process = _process(tmp_path, lines)
    endpoint = _StuckWriterEndpoint(
        [
            OSError(errno.ECONNABORTED, "software caused connection abort"),
            TimeoutError("writer did not stop"),
        ]
    )
    try:
        process.serve_one(endpoint)
        failures_before = process.accept_failures
        process.serve_one(endpoint)
        failures_after = process.accept_failures
    finally:
        process.close()

    diagnostic = json.loads(lines[-1])
    assert failures_before == 1
    assert failures_after == 1
    assert diagnostic["event"] == "connection_failed"
    assert "writer did not stop" in diagnostic["error"]
