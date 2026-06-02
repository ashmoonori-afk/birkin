"""Background Esc-key listener — lets the REPL user abort a running turn.

While the agent works, the main thread is blocked inside ``session.ask``; so a
daemon thread watches the terminal for a single **Esc** (``0x1b``) press and
fires a callback (which sets ``session.abort`` -> the LLM stream stops / the CLI
subprocess is killed). No-op when stdin is not a TTY, so piped / non-interactive
runs and tests are unaffected.

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
    def stop(self) -> None:  # nothing to stop
        pass


def listen_for_esc(on_esc: Callable[[], None]):
    """Start watching for Esc; returns an object with ``.stop()``.

    No-op (returns a null listener) when stdin is not an interactive TTY.
    """
    try:
        if not sys.stdin.isatty():
            return _NullListener()
    except Exception:
        return _NullListener()
    try:
        return _WinListener(on_esc) if os.name == "nt" else _PosixListener(on_esc)
    except Exception:
        return _NullListener()


class _PosixListener:
    def __init__(self, on_esc: Callable[[], None]):
        import termios
        self._on_esc = on_esc
        self._stop = threading.Event()
        self._fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(self._fd)   # restored on stop()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self) -> None:
        import select
        import termios
        import tty
        try:
            tty.setcbreak(self._fd)               # char-at-a-time, no line buffer
            while not self._stop.is_set():
                r, _, _ = select.select([self._fd], [], [], 0.1)
                if r and os.read(self._fd, 1) == ESC.encode():
                    self._fire()
        except Exception:
            pass
        finally:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            except Exception:
                pass

    def _fire(self) -> None:
        try:
            self._on_esc()
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()
        self._t.join(timeout=0.3)


class _WinListener:
    def __init__(self, on_esc: Callable[[], None]):
        self._on_esc = on_esc
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self) -> None:
        import msvcrt
        while not self._stop.is_set():
            try:
                if msvcrt.kbhit():
                    if msvcrt.getwch() == ESC:
                        try:
                            self._on_esc()
                        except Exception:
                            pass
                else:
                    time.sleep(0.04)
            except Exception:
                time.sleep(0.1)

    def stop(self) -> None:
        self._stop.set()
        self._t.join(timeout=0.3)
