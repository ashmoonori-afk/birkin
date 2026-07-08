"""Tiny cross-platform arrow-key menu (standard library only).

``select`` renders a list you navigate with ↑/↓ (or j/k) and pick with Enter.
``confirm`` is a Yes/No variant. Both fall back to numbered ``input()`` when
stdin/stdout isn't a TTY (pipes, redirected output), so scripts still work.

Windows uses ``msvcrt``; POSIX uses ``termios``/``tty``. No third-party deps.
"""

from __future__ import annotations

import sys
from typing import Optional, Sequence

from .ui import CYAN, DIM, RESET

# Reuse the REPL's real VT-capability probe (it enables VT processing and reports
# whether that actually took). When the console can't honor the cursor-move/clear
# codes the arrow-key renderer relies on, ``select`` falls back to a numbered menu
# instead of drawing an invisible, un-navigable selector. ``_is_interactive`` and
# ``_read_event`` are shared with the REPL line editor — no need to re-implement
# raw msvcrt/termios key reading here.
from .inline_complete import _VT_OK, _is_interactive, _read_event


# -- key reading -----------------------------------------------------------

def _read_key() -> str:
    """Return one of: up, down, enter, cancel, other."""
    kind, value = _read_event()
    if kind in ("up", "down", "enter"):
        return kind
    if kind in ("ctrl_c", "ctrl_d", "esc"):
        return "cancel"
    if kind == "char":
        low = value.lower()
        if low == "k":
            return "up"
        if low == "j":
            return "down"
        if low == "q":
            return "cancel"
    return "other"


# -- public API ------------------------------------------------------------

def select(title: str, options: Sequence[str], default: int = 0) -> Optional[int]:
    """Show a menu; return the chosen index (or None if cancelled)."""
    options = list(options)
    if not options:
        return None
    if not _is_interactive() or not _VT_OK:
        return _select_fallback(title, options, default)

    idx = max(0, min(default, len(options) - 1))
    if title:
        print(title)
    print(f"{DIM}  ↑/↓ move · Enter select · q cancel{RESET}")
    for _ in options:  # reserve the option lines
        print()
    _render(options, idx)

    while True:
        key = _read_key()
        if key == "up":
            idx = (idx - 1) % len(options)
            _render(options, idx)
        elif key == "down":
            idx = (idx + 1) % len(options)
            _render(options, idx)
        elif key == "enter":
            return idx
        elif key == "cancel":
            return None


def confirm(question: str, default: bool = False) -> bool:
    labels = ["Yes", "No"]
    choice = select(question, labels, default=0 if default else 1)
    return choice == 0


# -- rendering -------------------------------------------------------------

def _render(options: list[str], idx: int) -> None:
    # Move cursor up to the first option line, then rewrite each in place.
    sys.stdout.write(f"\x1b[{len(options)}A")
    for i, opt in enumerate(options):
        cursor = f"{CYAN}❯{RESET}" if i == idx else " "
        text = f"{CYAN}{opt}{RESET}" if i == idx else opt
        sys.stdout.write(f"\r\x1b[2K  {cursor} {text}\n")
    sys.stdout.flush()


def _select_fallback(title: str, options: list[str], default: int) -> Optional[int]:
    if title:
        print(title)
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    try:
        raw = input(f"Choose [1-{len(options)}, default {default + 1}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not raw:
        return default
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return int(raw) - 1
    return default
