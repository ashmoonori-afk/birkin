"""Background interrupt listener — abort a running REPL turn with Esc or by
typing the next message.

While the agent works, the main thread is blocked inside ``session.ask``; so a
daemon thread watches the terminal:

- **Esc** -> interrupt now, discard anything typed.
- typing then **Enter** -> interrupt AND carry the typed line as the next
  message (``listener.pending_line``), so "start typing to interrupt" doesn't
  lose your text.

Fires ``on_interrupt`` once (sets ``session.abort`` -> the LLM stream stops / the
CLI subprocess is killed). No-op when stdin is not a TTY, so piped /
non-interactive runs and tests are unaffected.

Pure standard library (termios+select on POSIX, msvcrt on Windows).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable

ESC = "\x1b"


class _NullListener:
    pending_line = ""

    def stop(self) -> None:
        pass


def listen_for_interrupt(on_interrupt: Callable[[], None]):
    """Start watching for Esc / typed-line interrupt; returns a listener with
    ``.stop()`` and ``.pending_line``. No-op (null listener) when stdin is not a
    TTY."""
    try:
        if not sys.stdin.isatty():
            return _NullListener()
    except Exception:
        return _NullListener()
    try:
        return _WinListener(on_interrupt) if os.name == "nt" else _PosixListener(on_interrupt)
    except Exception:
        return _NullListener()


class _Base:
    def __init__(self, on_interrupt: Callable[[], None]):
        self._on_interrupt = on_interrupt
        self._stop = threading.Event()
        self._fired = False
        self._buf: list[str] = []
        self.pending_line = ""           # text typed before Enter (carried on)
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _handle(self, ch: str) -> None:
        """Feed one decoded character; trigger on Esc/Enter."""
        if self._fired:
            return
        if ch == ESC:
            self.pending_line = ""
            self._fire()
        elif ch in ("\r", "\n"):
            self.pending_line = "".join(self._buf)
            self._fire()
        elif ch in ("\x7f", "\x08"):     # backspace
            if self._buf:
                self._buf.pop()
        elif ch >= " ":                   # printable -> buffer for the next line
            self._buf.append(ch)

    def _fire(self) -> None:
        self._fired = True
        try:
            self._on_interrupt()
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()
        self._t.join(timeout=0.3)

    def _run(self) -> None:  # pragma: no cover - platform specific
        raise NotImplementedError


class _PosixListener(_Base):
    def __init__(self, on_interrupt):
        import termios
        self._fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(self._fd)   # restored on stop()
        super().__init__(on_interrupt)

    def _run(self) -> None:
        import select
        import termios
        import tty
        try:
            tty.setcbreak(self._fd)
            while not self._stop.is_set() and not self._fired:
                r, _, _ = select.select([self._fd], [], [], 0.1)
                if not r:
                    continue
                b = os.read(self._fd, 1)
                if not b:
                    continue
                ch = self._decode(b[0])
                if ch:
                    self._handle(ch)
        except Exception:
            pass
        finally:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            except Exception:
                pass

    def _decode(self, b0: int) -> str:
        """Assemble a UTF-8 char (so typed Korean/multibyte input survives)."""
        if b0 < 0x80:
            return chr(b0)
        n = 4 if b0 >= 0xF0 else 3 if b0 >= 0xE0 else 2 if b0 >= 0xC0 else 0
        if n == 0:
            return ""
        buf = bytes([b0]) + b"".join(os.read(self._fd, 1) for _ in range(n - 1))
        try:
            return buf.decode("utf-8", "ignore")
        except Exception:
            return ""


class _WinListener(_Base):
    def _run(self) -> None:
        import msvcrt
        while not self._stop.is_set() and not self._fired:
            try:
                if msvcrt.kbhit():
                    self._handle(msvcrt.getwch())   # wide char: Unicode-safe
                else:
                    time.sleep(0.04)
            except Exception:
                time.sleep(0.1)
