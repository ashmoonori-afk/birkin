"""Private Unix PTY descriptor ownership for Darwin terminals."""

from __future__ import annotations

import os
import select
import struct
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import final

from .contracts import ProtocolError, TerminalUnsupported


@final
@dataclass(frozen=True, slots=True)
class PtySupport:
    """Unix pseudo-terminal operations required by an owned descriptor."""

    open_pty: Callable[[], tuple[int, int]]
    set_nonblocking: Callable[[int], None]
    set_window_size: Callable[[int, int, int], None]


def load_pty_support() -> PtySupport:
    """Bind Unix PTY primitives without making them import requirements."""
    try:
        import fcntl
        import pty
        import termios
    except ModuleNotFoundError as exc:
        raise TerminalUnsupported(
            "terminal", "this platform does not provide Unix pseudo-terminals"
        ) from exc

    def set_nonblocking(descriptor: int) -> None:
        flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        _ = fcntl.fcntl(descriptor, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def set_window_size(descriptor: int, columns: int, rows: int) -> None:
        packed = struct.pack("HHHH", rows, columns, 0, 0)
        _ = fcntl.ioctl(descriptor, termios.TIOCSWINSZ, packed)

    return PtySupport(pty.openpty, set_nonblocking, set_window_size)


@final
class DarwinPtyDescriptor:
    """Own one configured nonblocking PTY master descriptor."""

    def __init__(self, descriptor: int, support: PtySupport) -> None:
        self._descriptor: int | None = descriptor
        self._support = support
        self._lock = threading.Lock()

    def read(self, max_bytes: int, timeout: float) -> bytes:
        if max_bytes <= 0 or timeout < 0:
            raise ProtocolError("terminal read bounds are invalid")
        descriptor = self._open_descriptor()
        readable, _, _ = select.select([descriptor], [], [], timeout)
        chunks = bytearray()
        while readable and len(chunks) < max_bytes:
            try:
                chunk = os.read(descriptor, min(4_096, max_bytes - len(chunks)))
            except (BlockingIOError, OSError):
                break
            if not chunk:
                break
            chunks.extend(chunk)
            readable, _, _ = select.select([descriptor], [], [], 0)
        return bytes(chunks)

    def write(self, data: bytes, timeout: float) -> None:
        if not data or timeout < 0:
            raise ProtocolError("terminal input bounds are invalid")
        descriptor = self._open_descriptor()
        view = memoryview(data)
        while view:
            try:
                written = os.write(descriptor, view)
            except BlockingIOError:
                _, writable, _ = select.select([], [descriptor], [], timeout)
                if not writable:
                    raise ProtocolError("terminal input write timed out") from None
                continue
            view = view[written:]

    def resize(self, columns: int, rows: int) -> None:
        self._support.set_window_size(self._open_descriptor(), columns, rows)

    def close(self) -> None:
        with self._lock:
            descriptor, self._descriptor = self._descriptor, None
        if descriptor is not None:
            os.close(descriptor)

    def _open_descriptor(self) -> int:
        with self._lock:
            descriptor = self._descriptor
        if descriptor is None:
            raise BrokenPipeError
        return descriptor


@final
class DarwinPtyPair:
    """Own setup descriptors until the configured master is transferred."""

    def __init__(self, master: int, slave: int, support: PtySupport) -> None:
        self._master: int | None = master
        self._slave: int | None = slave
        self._support = support

    @property
    def slave_path(self) -> str:
        if self._slave is None:
            raise BrokenPipeError
        return os.ttyname(self._slave)

    def transfer(self, columns: int, rows: int) -> DarwinPtyDescriptor:
        if self._master is None:
            raise BrokenPipeError
        master, self._master = self._master, None
        try:
            self._support.set_window_size(master, columns, rows)
            self._support.set_nonblocking(master)
            descriptor = DarwinPtyDescriptor(master, self._support)
        except OSError:
            os.close(master)
            raise
        self._close_slave()
        return descriptor

    def close(self) -> None:
        self._close_slave()
        if self._master is not None:
            master, self._master = self._master, None
            os.close(master)

    def _close_slave(self) -> None:
        if self._slave is not None:
            slave, self._slave = self._slave, None
            os.close(slave)


def open_darwin_pty() -> DarwinPtyPair:
    """Acquire one PTY pair under a rollback owner."""
    support = load_pty_support()
    master, slave = support.open_pty()
    return DarwinPtyPair(master, slave, support)
