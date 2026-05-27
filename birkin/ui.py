"""Shared terminal UI helpers (ANSI styling, streaming, tool-event printer).

Kept separate so both the REPL and the slash-command handlers render
identically without importing each other.
"""

from __future__ import annotations

import json
import sys
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
