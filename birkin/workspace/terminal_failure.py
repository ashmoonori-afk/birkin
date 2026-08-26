from __future__ import annotations

from collections.abc import Callable

from .terminal_output import TerminalOutputBatch, TerminalOutputPump
from .terminal_process import TerminalProcess


def teardown_failed_terminal(
    original: Exception,
    process: TerminalProcess,
    pump: TerminalOutputPump,
    drain_consume: Callable[[float], TerminalOutputBatch],
) -> None:
    try:
        pump.stop()
        process.close(1)
        pump.join()
        _ = drain_consume(0.0)
    except Exception as teardown_error:
        raise original from teardown_error
