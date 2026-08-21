"""Injectable process enumeration backed by thin psutil adapters."""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Iterable
from typing import Protocol, final, runtime_checkable

import psutil


@runtime_checkable
class ProcessHandle(Protocol):
    def username(self) -> str | None: ...

    def pid(self) -> int: ...

    def name(self) -> str: ...

    def cmdline(self) -> str: ...

    def cwd(self) -> str: ...

    def open_files(self) -> tuple[str, ...]: ...


@runtime_checkable
class ProcessSource(Protocol):
    def current_username(self) -> str: ...

    def processes(self) -> Iterable[ProcessHandle]: ...


@final
class PsutilProcessHandle:
    def __init__(self, process: psutil.Process) -> None:
        self._process = process

    def username(self) -> str | None:
        return self._process.username()

    def pid(self) -> int:
        return self._process.pid

    def name(self) -> str:
        return self._process.name()

    def cmdline(self) -> str:
        arguments = self._process.cmdline()
        if os.name == "nt":
            return subprocess.list2cmdline(arguments)
        return shlex.join(arguments)

    def cwd(self) -> str:
        return self._process.cwd()

    def open_files(self) -> tuple[str, ...]:
        return tuple(entry.path for entry in self._process.open_files())


@final
class PsutilProcessSource:
    def current_username(self) -> str:
        return psutil.Process().username()

    def processes(self) -> Iterable[ProcessHandle]:
        for process in psutil.process_iter():
            yield PsutilProcessHandle(process)
