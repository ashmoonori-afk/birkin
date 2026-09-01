"""Event-driven pexpect-compatible adapter over Windows ConPTY."""

from __future__ import annotations

import os
import queue
import re
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO, TypeAlias, final

import pexpect
from typing_extensions import override


class _CancelableIo(Protocol):
    def cancel_io(self) -> bool: ...


class _RawPtyProcess(Protocol):
    @property
    def pty(self) -> _CancelableIo: ...

    @property
    def pid(self) -> int | None: ...

    @property
    def exitstatus(self) -> int | None: ...

    def read(self, size: int = 1024) -> str: ...

    def write(self, s: str) -> int: ...

    def setwinsize(self, rows: int, cols: int) -> None: ...

    def terminate(self, force: bool = False) -> bool | None: ...

    def close(self, force: bool = False) -> None: ...

    def isalive(self) -> bool: ...

    def wait(self) -> int | None: ...


@dataclass(frozen=True, slots=True)
class ConptySpawnError(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class _Chunk:
    text: str


@dataclass(frozen=True, slots=True)
class _End:
    error: str | None


_ReaderEvent: TypeAlias = _Chunk | _End


@final
class ConptySpawn:
    """Mutable terminal cursor and process state for one ConPTY child."""

    def __init__(
        self,
        process: _RawPtyProcess,
        *,
        encoding: str,
        timeout: float,
    ) -> None:
        if process.pid is None:
            raise ConptySpawnError("ConPTY child has no process identifier")
        self._process = process
        self._pid = process.pid
        if encoding.lower().replace("_", "-") != "utf-8":
            raise ConptySpawnError("ConPTY supports UTF-8 text only")
        self.timeout = timeout
        self.logfile_read: TextIO | None = None
        self.match: re.Match[str] | None = None
        self.before = ""
        self.after = ""
        self._buffer = ""
        self._events: queue.Queue[_ReaderEvent] = queue.Queue()
        self._ended = False
        self._closing = threading.Event()
        self._reader = threading.Thread(
            target=self._read_chunks,
            name=f"birkin-conpty-reader-{self._pid}",
            daemon=True,
        )
        self._waiter = threading.Thread(
            target=self._wait_for_process,
            name=f"birkin-conpty-waiter-{self._pid}",
            daemon=True,
        )
        self._reader.start()
        self._waiter.start()

    @classmethod
    def spawn(
        cls,
        command: str,
        args: Sequence[str] = (),
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        timeout: float = 30,
        dimensions: tuple[int, int] = (24, 80),
    ) -> ConptySpawn:
        """Start a UTF-8 child attached to a native Windows pseudo-console."""
        from winpty import PtyProcess

        child_env = dict(os.environ if env is None else env)
        child_env["PYTHONUTF8"] = "1"
        child_env["PYTHONIOENCODING"] = "utf-8"
        raw_process: _RawPtyProcess = PtyProcess.spawn(
            [command, *args],
            cwd=None if cwd is None else str(cwd),
            env=child_env,
            dimensions=dimensions,
        )
        return cls(raw_process, encoding=encoding, timeout=timeout)

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def exitstatus(self) -> int | None:
        _ = self._process.isalive()
        return self._process.exitstatus

    @property
    def reader_alive(self) -> bool:
        return self._reader.is_alive() or self._waiter.is_alive()

    def set_logfile_read(self, logfile: TextIO | None) -> None:
        """Route subsequently consumed output to the active text log."""
        self.logfile_read = logfile

    def matched_group(self, index: int) -> str:
        """Return one group from the latest regular-expression match."""
        if self.match is None:
            raise ConptySpawnError("ConPTY has no regular-expression match")
        return self.match.group(index)

    def send(self, value: str) -> int:
        """Write terminal input and return the number of characters accepted."""
        return self._process.write(value)

    def setwinsize(self, rows: int, columns: int) -> None:
        """Resize the native pseudo-console."""
        self._process.setwinsize(rows, columns)

    def expect_exact(self, pattern: str, timeout: float | None = None) -> int:
        """Consume through an exact string or raise a bounded diagnostic."""
        return self._expect(pattern, exact=True, timeout=timeout)

    def expect(self, pattern: str, timeout: float | None = None) -> int:
        """Consume through a regular expression."""
        return self._expect(pattern, exact=False, timeout=timeout)

    def expect_eof(self, timeout: float | None = None) -> None:
        """Drain every queued reader chunk before accepting EOF."""
        self._wait_for_eof(timeout)

    def terminate(self, force: bool = False) -> bool:
        """Terminate the exact ConPTY child; True when the child exited."""
        return bool(self._process.terminate(force=force))

    def close(self, force: bool = False) -> None:
        """Close the exact ConPTY process and await reader termination."""
        self._closing.set()
        self._process.close(force=force)
        self._reader.join(timeout=self.timeout)
        self._waiter.join(timeout=self.timeout)
        if self.reader_alive:
            raise pexpect.TIMEOUT("ConPTY reader did not terminate")

    def isalive(self) -> bool:
        """Return whether the exact spawned process remains alive."""
        return self._process.isalive()

    def _wait_for_process(self) -> None:
        from winpty import WinptyError

        _ = self._process.wait()
        if self._reader.is_alive():
            try:
                _ = self._process.pty.cancel_io()
            except WinptyError:
                return

    def _read_chunks(self) -> None:
        control_tail = ""
        try:
            while True:
                text = self._process.read(4096)
                controls = control_tail + text
                if "\x1b[c" in controls:
                    _ = self._process.write("\x1b[?1;2c")
                control_tail = controls[-2:]
                if text:
                    self._events.put(_Chunk(text))
        except EOFError:
            self._events.put(_End(None))
        except OSError as exc:
            clean_end = self._closing.is_set() or not self._process.isalive()
            error = None if clean_end else f"{type(exc).__name__}: {exc}"
            self._events.put(_End(error))

    def _next_event(self, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise queue.Empty
        event = self._events.get(timeout=remaining)
        match event:
            case _Chunk(text=text):
                if self.logfile_read is not None:
                    _ = self.logfile_read.write(text)
                self._buffer += text
            case _End(error=error):
                self._ended = True
                if error is not None:
                    raise pexpect.EOF(f"ConPTY reader failed: {error}")

    def _expect(
        self,
        pattern: str,
        *,
        exact: bool,
        timeout: float | None,
    ) -> int:
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            if exact:
                found = self._buffer.find(pattern)
                if found >= 0:
                    self.before = self._buffer[:found]
                    end = found + len(pattern)
                    self.after = self._buffer[found:end]
                    self.match = None
                    self._buffer = self._buffer[end:]
                    return 0
            else:
                regex_match = re.search(pattern, self._buffer)
                if regex_match is not None:
                    self.before = self._buffer[: regex_match.start()]
                    self.after = self._buffer[regex_match.start() : regex_match.end()]
                    self.match = regex_match
                    self._buffer = self._buffer[regex_match.end() :]
                    return 0
            if self._ended:
                raise pexpect.EOF(self._diagnostic("EOF", pattern))
            try:
                self._next_event(deadline)
            except queue.Empty as exc:
                raise pexpect.TIMEOUT(
                    self._diagnostic("timeout", pattern)
                ) from exc

    def _wait_for_eof(self, timeout: float | None) -> None:
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while not self._ended:
            try:
                self._next_event(deadline)
            except queue.Empty as exc:
                raise pexpect.TIMEOUT(
                    self._diagnostic("timeout waiting for EOF", "EOF")
                ) from exc
        self.before = self._buffer
        self.after = "EOF"
        self._buffer = ""
        self._reader.join(timeout=max(0.0, deadline - time.monotonic()))

    def _diagnostic(self, reason: str, pattern: str) -> str:
        trailing = self._buffer[-500:]
        return f"ConPTY {reason}; pattern={pattern!r}; trailing={trailing!r}"
