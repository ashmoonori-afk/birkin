"""Inline slash-command autocomplete for the birkin REPL — stdlib only.

When the user types ``/`` at the prompt, a live dropdown appears below the
input line showing matching commands. The selection moves with ↑/↓; **Tab**
inserts the selected command (with a trailing space for arguments); **Enter**
submits the current line as-is; **Esc** dismisses the dropdown (the typed text
is kept). For non-slash input the prompt behaves like a normal line editor.

Cross-platform: POSIX termios / Windows msvcrt, no third-party deps. On
non-TTY stdin/stdout (pipes, redirected input, CI) it falls back transparently
to plain ``input()`` so scripts and tests are unaffected.

The matching and rendering logic are isolated as pure functions
(:func:`filter_commands`, :func:`render_menu_lines`) so they're directly
unit-testable; the raw I/O loop is the only side-effecting part.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

# Lazy ANSI imports — keep this module usable without ui.py being importable
# during early tests.
try:
    from .ui import CYAN, DIM, RESET
except Exception:  # pragma: no cover - defensive
    CYAN = DIM = RESET = ""

# Best-effort enable ANSI on legacy Windows consoles.
if os.name == "nt":
    os.system("")

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


# -- public, pure helpers ---------------------------------------------------

@dataclass(frozen=True)
class CommandHint:
    """Subset of a slash command needed for autocomplete display."""
    name: str
    summary: str


def filter_commands(buffer: str, commands: Sequence[CommandHint]) -> list[CommandHint]:
    """Return the dropdown candidates for the current input buffer.

    Rules:
    - Buffer that doesn't start with ``/`` -> no dropdown.
    - Buffer that already contains whitespace (e.g. ``/skill `` plus args) ->
      no dropdown; the user has committed to a command and is typing args.
    - Otherwise rank ``starts-with`` matches before substring matches, both
      case-insensitive. Bare ``/`` lists every command.
    """
    if not buffer.startswith("/"):
        return []
    tail = buffer[1:]
    if any(ch.isspace() for ch in tail):
        return []
    needle = tail.lower()
    if not needle:
        return list(commands)
    starts = [c for c in commands if c.name.lower().startswith(needle)]
    subs = [c for c in commands
            if needle in c.name.lower() and c not in starts]
    return starts + subs


def common_prefix(strings: Iterable[str]) -> str:
    """Longest common case-sensitive prefix of ``strings`` (empty if none)."""
    it = iter(strings)
    try:
        cp = next(it)
    except StopIteration:
        return ""
    for s in it:
        n = min(len(cp), len(s))
        i = 0
        while i < n and cp[i] == s[i]:
            i += 1
        cp = cp[:i]
        if not cp:
            return ""
    return cp


def render_menu_lines(matches: Sequence[CommandHint], selected: int,
                      max_show: int = 8) -> list[str]:
    """Render the dropdown as a list of ANSI-styled lines (no trailing newline).

    The first ``max_show`` matches are shown; an extra "+ N more" line is added
    if the list is longer. ``selected`` is the highlighted index (clamped).
    """
    if not matches:
        return []
    shown = list(matches[:max_show])
    sel = max(0, min(selected, len(shown) - 1))
    out: list[str] = []
    for i, c in enumerate(shown):
        cursor = f"{CYAN}❯{RESET}" if i == sel else " "
        name = f"{CYAN}/{c.name}{RESET}" if i == sel else f"/{c.name}"
        summary = f"{DIM}{c.summary}{RESET}" if c.summary else ""
        out.append(f"  {cursor} {name}  {summary}")
    extra = len(matches) - len(shown)
    if extra > 0:
        out.append(f"  {DIM}… +{extra} more (keep typing to filter){RESET}")
    return out


def visible_len(s: str) -> int:
    """String width as it appears on screen (ANSI escapes stripped)."""
    return len(_ANSI_RE.sub("", s))


# -- I/O loop ---------------------------------------------------------------

def _is_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _read_event_posix() -> tuple[str, str]:
    """One key read on POSIX. Returns (kind, value).

    Multi-byte UTF-8 sequences are reassembled here so a single typed character
    arrives as one ``("char", ch)`` event even for non-ASCII input.
    """
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        b = os.read(fd, 1)
        if not b:
            return ("ctrl_d", "")
        c = b[0]
        if c == 0x03:
            return ("ctrl_c", "")
        if c == 0x04:
            return ("ctrl_d", "")
        if c in (0x0a, 0x0d):
            return ("enter", "")
        if c == 0x09:
            return ("tab", "")
        if c in (0x7f, 0x08):
            return ("backspace", "")
        if c == 0x1b:
            # CSI escape (arrows) or bare ESC
            seq = os.read(fd, 2)
            if seq == b"[A":
                return ("up", "")
            if seq == b"[B":
                return ("down", "")
            if seq == b"[C":
                return ("right", "")
            if seq == b"[D":
                return ("left", "")
            return ("esc", "")
        # ASCII printable
        if 0x20 <= c < 0x80:
            return ("char", chr(c))
        # Multi-byte UTF-8 leading byte → read continuation bytes
        if c & 0xE0 == 0xC0:
            extra = 1
        elif c & 0xF0 == 0xE0:
            extra = 2
        elif c & 0xF8 == 0xF0:
            extra = 3
        else:
            return ("other", "")
        rest = os.read(fd, extra)
        try:
            return ("char", (bytes([c]) + rest).decode("utf-8"))
        except UnicodeDecodeError:
            return ("other", "")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_event_windows() -> tuple[str, str]:
    import msvcrt
    ch = msvcrt.getwch()
    if ch == "\x03":
        return ("ctrl_c", "")
    if ch == "\x04":
        return ("ctrl_d", "")
    if ch in ("\r", "\n"):
        return ("enter", "")
    if ch == "\t":
        return ("tab", "")
    if ch == "\x08":
        return ("backspace", "")
    if ch == "\x1b":
        return ("esc", "")
    if ch in ("\x00", "\xe0"):
        code = msvcrt.getwch()
        return ({"H": "up", "P": "down", "K": "left", "M": "right"}
                .get(code, "other"), "")
    # msvcrt.getwch returns a wide character, so multi-byte input
    # (e.g. Hangul) arrives as a single character already.
    return ("char", ch)


def _read_event() -> tuple[str, str]:
    return _read_event_windows() if os.name == "nt" else _read_event_posix()


def _clear_menu(prev_lines: int) -> None:
    """Erase ``prev_lines`` menu rows below the current cursor and return to
    the input line (cursor at end of input)."""
    if prev_lines <= 0:
        return
    for _ in range(prev_lines):
        sys.stdout.write("\n\x1b[2K")
    sys.stdout.write(f"\x1b[{prev_lines}A")
    sys.stdout.flush()


def _redraw(prompt: str, buffer: str, menu_lines: list[str],
            prev_menu_lines: int) -> int:
    """Redraw the input line and the dropdown menu below it.

    Returns the new menu-line count so the next redraw can erase it.
    """
    # 1. Clear any leftover menu rows below us.
    _clear_menu(prev_menu_lines)
    # 2. Rewrite the input line in place.
    sys.stdout.write("\r\x1b[2K")
    sys.stdout.write(prompt + buffer)
    # 3. Draw the menu (each line on its own row), then jump back up so the
    #    cursor sits at the end of the input line again.
    n = len(menu_lines)
    if n:
        sys.stdout.write("\n")
        for i, line in enumerate(menu_lines):
            sys.stdout.write("\x1b[2K" + line)
            if i < n - 1:
                sys.stdout.write("\n")
        sys.stdout.write(f"\x1b[{n}A")
        # cursor column = visible(prompt) + len(buffer) + 1
        col = visible_len(prompt) + len(buffer) + 1
        sys.stdout.write(f"\r\x1b[{col}G")
    sys.stdout.flush()
    return n


def prompt_with_completion(prompt: str,
                           commands: Sequence[CommandHint]) -> Optional[str]:
    """Read one input line from the user with inline ``/cmd`` autocomplete.

    Returns the entered string, or ``None`` on Ctrl-C / EOF (the caller treats
    this as ``KeyboardInterrupt`` equivalent). On non-TTY input falls back to
    :func:`input` so pipes and tests work unchanged.
    """
    if not _is_interactive():
        try:
            return input(prompt)
        except (EOFError, KeyboardInterrupt):
            return None

    buffer = ""
    selected = 0
    menu_dismissed = False
    prev_menu_lines = 0

    sys.stdout.write(prompt)
    sys.stdout.flush()

    while True:
        if menu_dismissed:
            matches: list[CommandHint] = []
        else:
            matches = filter_commands(buffer, commands)
        menu_lines = render_menu_lines(matches, selected) if matches else []
        prev_menu_lines = _redraw(prompt, buffer, menu_lines, prev_menu_lines)

        kind, value = _read_event()

        if kind == "ctrl_c":
            _clear_menu(prev_menu_lines)
            sys.stdout.write("\n")
            sys.stdout.flush()
            return None
        if kind == "ctrl_d":
            if not buffer:
                _clear_menu(prev_menu_lines)
                sys.stdout.write("\n")
                sys.stdout.flush()
                return None
            continue  # ignore mid-line
        if kind == "enter":
            _clear_menu(prev_menu_lines)
            sys.stdout.write("\n")
            sys.stdout.flush()
            return buffer
        if kind == "backspace":
            if buffer:
                buffer = buffer[:-1]
                selected = 0
                menu_dismissed = False
            continue
        if kind == "char":
            buffer += value
            selected = 0
            menu_dismissed = False
            continue
        if kind == "tab":
            if matches:
                # If a unique match (or selection is explicit) -> commit it.
                # Otherwise -> extend buffer to the longest common prefix.
                if len(matches) == 1 or selected > 0:
                    chosen = matches[selected if selected < len(matches) else 0]
                    buffer = f"/{chosen.name} "
                    menu_dismissed = True
                else:
                    cp = common_prefix(c.name for c in matches)
                    candidate = f"/{cp}"
                    if len(candidate) > len(buffer):
                        buffer = candidate
                selected = 0
            continue
        if kind == "up":
            if matches:
                selected = (selected - 1) % len(matches)
            continue
        if kind == "down":
            if matches:
                selected = (selected + 1) % len(matches)
            continue
        if kind == "esc":
            menu_dismissed = True
            continue
        # left/right/other -> ignore (cursor stays at end; first-rev minimalism)


# -- adapter for the REPL ---------------------------------------------------

def hints_from_registry(registry: dict) -> list[CommandHint]:
    """Convert birkin.slashcommands._REGISTRY into CommandHint list.

    Skips alias-only entries; sorts by name for stable display.
    """
    out: list[CommandHint] = []
    seen: set[str] = set()
    for name, cmd in registry.items():
        if name in seen:
            continue
        seen.add(name)
        out.append(CommandHint(name=name, summary=getattr(cmd, "summary", "")))
    out.sort(key=lambda h: h.name)
    return out
