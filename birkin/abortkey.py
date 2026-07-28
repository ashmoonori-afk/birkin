"""Background interrupt listener — abort a running REPL turn with Esc or by
typing the next message.

While the agent works, the main thread is blocked inside ``session.ask``; so a
daemon thread watches the terminal:

- **Esc** -> interrupt now, discard anything typed.
- typing then **Enter** -> hand the line to ``on_line`` if one is given. When
  that callback accepts it (a *steer*: the running turn takes the instruction
  and keeps its work), the listener stays live so more lines can follow.
  Otherwise the original behavior applies: interrupt AND carry the typed line
  as the next message (``listener.pending_line``).

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
from typing import Callable, Optional

ESC = "\x1b"


class _NullListener:
    pending_line = ""

    def stop(self) -> None:
        pass


def listen_for_interrupt(on_interrupt: Callable[[], None],
                         on_line: Optional[Callable[[str], bool]] = None):
    """Start watching for Esc / typed-line input; returns a listener with
    ``.stop()`` and ``.pending_line``. No-op (null listener) when stdin is not a
    TTY.

    ``on_line`` receives a completed typed line and returns True if it was
    consumed as a steer — in which case the turn is NOT interrupted.
    """
    try:
        if not sys.stdin.isatty():
            return _NullListener()
    except Exception:
        return _NullListener()
    try:
        cls = _WinListener if os.name == "nt" else _PosixListener
        return cls(on_interrupt, on_line)
    except Exception:
        return _NullListener()


class _Base:
    # Class-level default so an instance built without __init__ (tests drive
    # _handle directly) still behaves as "no steering configured".
    _on_line: Optional[Callable[[str], bool]] = None

    def __init__(self, on_interrupt: Callable[[], None],
                 on_line: Optional[Callable[[str], bool]] = None):
        self._on_interrupt = on_interrupt
        self._on_line = on_line
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
            line = "".join(self._buf)
            if line.strip() and self._on_line is not None:
                try:
                    steered = bool(self._on_line(line))
                except Exception:
                    steered = False
                if steered:
                    # Consumed by the running turn. Keep listening so the user
                    # can steer again, and leave Esc as the way to kill it.
                    self._buf.clear()
                    return
            self.pending_line = line
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
    def __init__(self, on_interrupt, on_line=None):
        import termios
        self._fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(self._fd)   # restored on stop()
        super().__init__(on_interrupt, on_line)

    def _run(self) -> None:
        import codecs
        import select
        import termios
        import tty
        # Incremental UTF-8 decode so typed Korean/multibyte input survives
        # (returns "" until a full char's bytes have arrived).
        decoder = codecs.getincrementaldecoder("utf-8")("ignore")
        try:
            tty.setcbreak(self._fd)
            while not self._stop.is_set() and not self._fired:
                r, _, _ = select.select([self._fd], [], [], 0.1)
                if not r:
                    continue
                b = os.read(self._fd, 1)
                if not b:
                    continue
                ch = decoder.decode(b)
                if ch:
                    self._handle(ch)
        except Exception:
            pass
        finally:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            except Exception:
                pass


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
