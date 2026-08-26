"""Platform-neutral ownership contract for interactive terminal processes."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, TypeAlias

from .contracts import TerminalUnsupported


class TerminalProcess(Protocol):
    """A contained terminal process tree with bounded synchronous I/O."""

    @property
    def pid(self) -> int: ...

    def poll(self) -> int | None: ...

    def read(self, max_bytes: int, timeout: float) -> bytes: ...

    def write(self, data: bytes, timeout: float) -> None: ...

    def resize(self, columns: int, rows: int) -> None: ...

    def signal(self, name: str) -> None: ...

    def close(self, exit_code: int = 1) -> None: ...


TerminalProcessFactory: TypeAlias = Callable[
    [Path, Path, Mapping[str, str], int, int], TerminalProcess
]


def launch_terminal_process(
    shell_path: Path,
    cwd: Path,
    environment: Mapping[str, str],
    columns: int,
    rows: int,
) -> TerminalProcess:
    """Launch the supported native backend selected by the running platform."""
    match sys.platform:
        case "darwin":
            from .darwin_terminal_process import launch_darwin_terminal_process

            return launch_darwin_terminal_process(
                shell_path, cwd, environment, columns, rows
            )
        case "win32":
            from .windows_conpty import (
                conpty_supported,
                launch_windows_terminal_process,
            )

            if conpty_supported():
                return launch_windows_terminal_process(
                    shell_path, cwd, dict(environment), columns, rows
                )
            raise TerminalUnsupported(
                "terminal", "this Windows build does not support ConPTY"
            )
        case _:
            raise TerminalUnsupported(
                "terminal", "this platform has no contained terminal backend"
            )
