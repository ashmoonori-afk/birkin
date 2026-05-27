"""Shared terminal UI helpers (ANSI styling, streaming, tool-event printer).

Kept separate so both the REPL and the slash-command handlers render
identically without importing each other.
"""

from __future__ import annotations

import itertools
import json
import sys
import threading
import time
from typing import Any, Callable

DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def stream_text(piece: str) -> None:
    sys.stdout.write(piece)
    sys.stdout.flush()


class Spinner:
    """A minimal 'thinking…' indicator for non-streaming waits.

    Runs in a daemon thread; ``stop()`` clears the line. Safe to stop twice.
    """

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label: str = "thinking…"):
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        for frame in itertools.cycle(self._FRAMES):
            if self._stop.wait(0.09):
                break
            sys.stdout.write(f"\r{DIM}{frame} {self.label}{RESET} ")
            sys.stdout.flush()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=0.3)
        self._thread = None
        sys.stdout.write("\r" + " " * (len(self.label) + 6) + "\r")
        sys.stdout.flush()


def make_event_printer() -> Callable[[str, dict[str, Any]], None]:
    """Return an on_event callback that prints compact tool activity."""
    def emit(event: str, payload: dict[str, Any]) -> None:
        if event == "tool_start":
            inp = json.dumps(payload.get("input", {}), ensure_ascii=False)
            if len(inp) > 80:
                inp = inp[:80] + "…"
            sys.stdout.write(f"\n{DIM}  → {payload.get('name')} {inp}{RESET}\n")
        elif event == "tool_end":
            mark = f"{RED}✗{RESET}" if payload.get("is_error") else f"{GREEN}✓{RESET}"
            sys.stdout.write(f"{DIM}  {mark} {payload.get('name')}{RESET}\n")
        elif event == "subagent.start":
            sys.stdout.write(f"\n{DIM}  ⇲ subagent: {payload.get('task', '')}{RESET}\n")
        elif event == "subagent.done":
            sys.stdout.write(f"{DIM}  ⇱ subagent done{RESET}\n")
        sys.stdout.flush()
    return emit
