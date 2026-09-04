"""Unix PTY primitives and one owned terminal process session."""

from __future__ import annotations

import codecs
import errno
import os
import select
import signal
import struct
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import final

from .contracts import ProtocolError, TerminalUnsupported
from .darwin_terminal_process import (
    DarwinTerminalProcess,
    terminate_darwin_terminal,
)

MAX_INPUT_BYTES = 4_096
MAX_OUTPUT_BYTES = 16_384
MAX_SCREEN_BYTES = 65_536
_SIGNAL_NAMES = ("INT", "TERM", "HUP")


@final
@dataclass(frozen=True, slots=True)
class PtySupport:
    """The Unix pseudo-terminal operations an owned process tree needs."""

    open_pty: Callable[[], tuple[int, int]]
    set_nonblocking: Callable[[int], None]
    set_window_size: Callable[[int, int, int], None]


def load_pty_support() -> PtySupport:
    """Bind Unix PTY primitives, or refuse with a typed capability error."""
    try:
        import fcntl
        import pty
        import termios
    except ModuleNotFoundError as exc:
        raise TerminalUnsupported(
            "terminal",
            "this platform does not provide Unix pseudo-terminals",
        ) from exc

    def set_nonblocking(descriptor: int) -> None:
        flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        _ = fcntl.fcntl(descriptor, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def set_window_size(descriptor: int, columns: int, rows: int) -> None:
        packed = struct.pack("HHHH", rows, columns, 0, 0)
        _ = fcntl.ioctl(descriptor, termios.TIOCSWINSZ, packed)

    return PtySupport(
        open_pty=pty.openpty,
        set_nonblocking=set_nonblocking,
        set_window_size=set_window_size,
    )


def allowed_signals() -> dict[str, signal.Signals]:
    """Project only the process-tree signals this platform actually defines."""
    table: dict[str, signal.Signals] = {}
    for name in _SIGNAL_NAMES:
        value = getattr(signal, f"SIG{name}", None)
        if isinstance(value, signal.Signals):
            table[name] = value
    return table


@dataclass(slots=True)
class TerminalSession:
    """Mutable PTY and lease state owned for one live process tree."""

    terminal_id: str
    process: DarwinTerminalProcess
    master_fd: int
    pty: PtySupport
    cwd: Path
    lease: str | None
    lease_expires_at: float
    monotonic: Callable[[], float]
    input_sequence: int = 0
    output_sequence: int = 0
    screen: str = ""
    exited_emitted: bool = False
    released: bool = False
    _decoder: codecs.IncrementalDecoder = field(
        default_factory=lambda: codecs.getincrementaldecoder("utf-8")(
            errors="replace"
        ),
        repr=False,
    )
    _read_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def pump_output(
        self,
        *,
        timeout: float,
        consume: Callable[[bytes, bool], None] | None = None,
    ) -> tuple[bytes, bool]:
        """Read one bounded batch while tolerating quiet gaps before deadline."""
        chunks = bytearray()
        reached_eof = False
        deadline = time.monotonic() + timeout
        with self._read_lock:
            while len(chunks) < MAX_OUTPUT_BYTES and not self.released:
                remaining = max(0.0, deadline - time.monotonic())
                ready, _, _ = select.select(
                    [self.master_fd], [], [], remaining
                )
                if not ready:
                    if remaining > 0:
                        continue
                    break
                try:
                    chunk = os.read(
                        self.master_fd,
                        min(4_096, MAX_OUTPUT_BYTES - len(chunks)),
                    )
                except BlockingIOError:
                    continue
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        reached_eof = True
                        break
                    raise
                if not chunk:
                    reached_eof = True
                    break
                chunks.extend(chunk)
                if consume is not None:
                    consume(chunk, False)
            if reached_eof and consume is not None:
                consume(b"", True)
        return bytes(chunks), reached_eof

    def read_output(self, *, timeout: float) -> bytes:
        """Compatibility projection for callers that only need raw bytes."""
        return self.pump_output(timeout=timeout)[0]

    def record_output(
        self,
        output: bytes,
        *,
        final: bool = False,
    ) -> dict[str, object]:
        text = self._decoder.decode(output, final=final)
        if text:
            self.output_sequence += 1
            encoded_screen = (self.screen + text).encode("utf-8")
            self.screen = encoded_screen[-MAX_SCREEN_BYTES:].decode(
                "utf-8", errors="ignore"
            )
        return {
            "terminal_id": self.terminal_id,
            "sequence": self.output_sequence,
            "data": text,
        }

    def write(self, data: bytes) -> None:
        view = memoryview(data)
        while view:
            try:
                written = os.write(self.master_fd, view)
            except BlockingIOError:
                _, writable, _ = select.select([], [self.master_fd], [], 1.0)
                if not writable:
                    raise ProtocolError("terminal input write timed out")
                continue
            view = view[written:]

    def terminate_process(self) -> None:
        terminate_darwin_terminal(self.process)

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        try:
            os.close(self.master_fd)
        except OSError:
            pass
        self.lease = None
