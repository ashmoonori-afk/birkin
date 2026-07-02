"""Tiny cross-platform arrow-key menu (standard library only).

``select`` renders a list you navigate with ↑/↓ (or j/k) and pick with Enter.
``confirm`` is a Yes/No variant. Both fall back to numbered ``input()`` when
stdin/stdout isn't a TTY (pipes, redirected output), so scripts still work.

Windows uses ``msvcrt``; POSIX uses ``termios``/``tty``. No third-party deps.
"""

from __future__ import annotations

import os
import sys
from typing import Optional, Sequence

from .ui import CYAN, DIM, RESET

# Reuse the REPL's real VT-capability probe (it enables VT processing and reports
# whether that actually took). When the console can't honor the cursor-move/clear
# codes the arrow-key renderer relies on, ``select`` falls back to a numbered menu
# instead of drawing an invisible, un-navigable selector.
from .inline_complete import _VT_OK


def _is_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


# -- key reading -----------------------------------------------------------

def _read_key() -> str:
    """Return one of: up, down, enter, cancel, other."""
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x03" or ch == "\x1b":
            return "cancel"
        if ch in ("\x00", "\xe0"):  # arrow prefix
            code = msvcrt.getwch()
            return {"H": "up", "P": "down"}.get(code, "other")
        if ch in ("k", "K"):
            return "up"
        if ch in ("j", "J"):
            return "down"
        if ch in ("q", "Q"):
            return "cancel"
        return "other"

    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x03":
            return "cancel"
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            if seq == "[A":
                return "up"
            if seq == "[B":
                return "down"
            return "cancel"
        if ch in ("k", "K"):
            return "up"
        if ch in ("j", "J"):
            return "down"
        if ch in ("q", "Q"):
            return "cancel"
        return "other"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


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
