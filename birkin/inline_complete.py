"""Inline slash-command autocomplete + line editor for the birkin REPL.

A stdlib-only line editor that activates a live ``/cmd`` dropdown the moment
the user types ``/``. Cursor motion (←/→, Home/End), in-place deletion
(Delete in addition to Backspace), and history navigation (↑/↓ when the
dropdown is not active) are all supported.

Architecture: state + transitions are pure functions
(:class:`EditorState`, :func:`apply_event`, plus the original filter/render
helpers). Only the raw-input and redraw functions touch I/O. This keeps the
bulk of behavior unit-testable offline.

Cross-platform: POSIX termios + Windows ``msvcrt``. UTF-8 multi-byte input
is reassembled on POSIX; ``msvcrt.getwch`` returns wide characters directly
on Windows. On non-TTY stdin/stdout the function transparently falls back to
plain :func:`input` so scripts, pipes, and pytest are unaffected.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

# Lazy ANSI imports — keep this module usable even if ui.py isn't importable
# during isolated tests.
try:
    from .ui import CYAN, DIM, RESET
except Exception:  # pragma: no cover - defensive
    CYAN = DIM = RESET = ""

# Best-effort enable ANSI on legacy Windows consoles.
if os.name == "nt":
    os.system("")

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_HISTORY_FILENAME = "repl_history.txt"
_HISTORY_LIMIT = 500


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
    - Buffer that already contains whitespace (the user is typing args) -> no
      dropdown.
    - Otherwise rank ``starts-with`` first, then substring matches (both
      case-insensitive). Bare ``/`` lists every command.
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
    """Render the dropdown as ANSI-styled lines (no trailing newline).

    Selection is clamped to a valid index so out-of-range values don't raise.
    A "+ N more" footer is added if the list exceeds ``max_show``.
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


# -- state machine (pure) ---------------------------------------------------

@dataclass
class EditorState:
    """One REPL line's editing state.

    Driven only via :func:`apply_event` — no method on this class touches I/O,
    so the whole edit loop is straightforwardly unit-testable.
    """
    buffer: str = ""
    cursor: int = 0        # 0 ≤ cursor ≤ len(buffer); cursor inserts here
    selected: int = 0      # index into the *current* filtered matches
    menu_dismissed: bool = False
    history_idx: int = -1  # -1 = not browsing; otherwise index into history
    pending: Optional[str] = None   # buffer the user had when they entered history
    submitted: Optional[str] = None # set on Enter; signals loop to exit
    exited: bool = False            # set on Ctrl-C / Ctrl-D-on-empty


def matches_for(state: EditorState, commands: Sequence[CommandHint]) -> list[CommandHint]:
    """Match list to render *given* the current state (honors `menu_dismissed`)."""
    if state.menu_dismissed:
        return []
    return filter_commands(state.buffer, commands)


def apply_event(state: EditorState, event: tuple[str, str],
                commands: Sequence[CommandHint],
                history: Sequence[str]) -> EditorState:
    """Advance ``state`` by one keyboard event. Mutates ``state`` and returns it
    (a typical builder pattern; treating each call as a transition is fine for
    tests since the dataclass is fully introspectable)."""
    kind, value = event

    if kind == "ctrl_c":
        state.exited = True
        return state
    if kind == "ctrl_d":
        if not state.buffer:
            state.exited = True
        return state
    if kind == "enter":
        state.submitted = state.buffer
        return state

    if kind == "char":
        state.buffer = state.buffer[:state.cursor] + value + state.buffer[state.cursor:]
        state.cursor += len(value)
        state.selected = 0
        state.menu_dismissed = False
        state.history_idx = -1
        state.pending = None
        return state

    if kind == "backspace":
        if state.cursor > 0:
            state.buffer = state.buffer[:state.cursor - 1] + state.buffer[state.cursor:]
            state.cursor -= 1
            state.selected = 0
            state.menu_dismissed = False
            state.history_idx = -1
            state.pending = None
        return state

    if kind == "delete":
        if state.cursor < len(state.buffer):
            state.buffer = state.buffer[:state.cursor] + state.buffer[state.cursor + 1:]
            state.selected = 0
            state.menu_dismissed = False
            state.history_idx = -1
            state.pending = None
        return state

    if kind == "left":
        if state.cursor > 0:
            state.cursor -= 1
        return state
    if kind == "right":
        if state.cursor < len(state.buffer):
            state.cursor += 1
        return state
    if kind == "home":
        state.cursor = 0
        return state
    if kind == "end":
        state.cursor = len(state.buffer)
        return state

    if kind == "tab":
        ms = matches_for(state, commands)
        if ms:
            # If the user navigated explicitly, commit the highlighted match.
            if state.selected > 0 and state.selected < len(ms):
                chosen = ms[state.selected]
                state.buffer = f"/{chosen.name} "
                state.cursor = len(state.buffer)
                state.menu_dismissed = True
            else:
                # Prefix extension should only consider starts-with matches —
                # substring matches in the dropdown are a discovery aid and
                # would otherwise drag the common prefix back to ``/``.
                tail = state.buffer[1:].lower()
                starts = [m for m in ms if m.name.lower().startswith(tail)]
                target = starts or ms
                if len(target) == 1:
                    state.buffer = f"/{target[0].name} "
                    state.cursor = len(state.buffer)
                    state.menu_dismissed = True
                else:
                    cp = common_prefix(c.name for c in target)
                    candidate = f"/{cp}"
                    if len(candidate) > len(state.buffer):
                        state.buffer = candidate
                        state.cursor = len(state.buffer)
            state.selected = 0
        return state

    if kind == "up":
        ms = matches_for(state, commands)
        if ms:
            state.selected = (state.selected - 1) % len(ms)
        else:
            _history_prev(state, history)
        return state

    if kind == "down":
        ms = matches_for(state, commands)
        if ms:
            state.selected = (state.selected + 1) % len(ms)
        else:
            _history_next(state, history)
        return state

    if kind == "esc":
        # First Esc: if browsing history, restore the pending buffer; else
        # just dismiss the dropdown but keep the typed text.
        if state.history_idx != -1:
            state.buffer = state.pending or ""
            state.cursor = len(state.buffer)
            state.history_idx = -1
            state.pending = None
        else:
            state.menu_dismissed = True
        return state

    return state   # unknown event — ignored


def _history_prev(state: EditorState, history: Sequence[str]) -> None:
    if not history:
        return
    if state.history_idx == -1:
        state.pending = state.buffer
        state.history_idx = len(history) - 1
    elif state.history_idx > 0:
        state.history_idx -= 1
    else:
        return
    state.buffer = history[state.history_idx]
    state.cursor = len(state.buffer)
    state.selected = 0
    state.menu_dismissed = False


def _history_next(state: EditorState, history: Sequence[str]) -> None:
    if state.history_idx == -1:
        return
    if state.history_idx + 1 >= len(history):
        state.history_idx = -1
        state.buffer = state.pending or ""
        state.cursor = len(state.buffer)
        state.pending = None
    else:
        state.history_idx += 1
        state.buffer = history[state.history_idx]
        state.cursor = len(state.buffer)
    state.selected = 0
    state.menu_dismissed = False


# -- history persistence ----------------------------------------------------

def _history_path() -> Optional[str]:
    """Path to the persistent REPL history file under the birkin home dir.

    Returns None if ``config.sessions_dir()`` is unavailable (e.g. partial
    test environments). The history file is plain text, one line per command.
    """
    try:
        from . import config
        return os.path.join(str(config.sessions_dir()), _HISTORY_FILENAME)
    except Exception:   # pragma: no cover - defensive
        return None


def load_history(path: Optional[str] = None, limit: int = _HISTORY_LIMIT) -> list[str]:
    """Load the persistent history file (or return ``[]`` if missing)."""
    p = path or _history_path()
    if not p or not os.path.isfile(p):
        return []
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            lines = [ln.rstrip("\n") for ln in fh.readlines()]
    except OSError:
        return []
    return [ln for ln in lines if ln][-limit:]


def append_history(line: str, path: Optional[str] = None,
                   prior: Optional[Sequence[str]] = None) -> None:
    """Append ``line`` to history, skipping blanks and consecutive duplicates."""
    if not line or line.isspace():
        return
    if prior and prior[-1] == line:
        return
    p = path or _history_path()
    if not p:
        return
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass   # silent — history is best-effort


# -- raw key reading --------------------------------------------------------

def _is_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _read_event_posix() -> tuple[str, str]:
    """One key read on POSIX, including CSI sequences for navigation keys."""
    import select
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
        if c == 0x01:
            return ("home", "")
        if c == 0x05:
            return ("end", "")
        if c in (0x0a, 0x0d):
            return ("enter", "")
        if c == 0x09:
            return ("tab", "")
        if c in (0x7f, 0x08):
            return ("backspace", "")
        if c == 0x1b:
            # CSI / SS3 sequence? Read more non-blockingly. If nothing
            # follows within ~30ms it's a bare Esc.
            ready, _, _ = select.select([fd], [], [], 0.03)
            if not ready:
                return ("esc", "")
            nb = os.read(fd, 1)
            if nb in (b"[", b"O"):
                seq = b""
                # Read until terminator (alpha letter or '~') or no more data.
                for _ in range(8):
                    rdy, _, _ = select.select([fd], [], [], 0.03)
                    if not rdy:
                        break
                    bb = os.read(fd, 1)
                    seq += bb
                    if bb.isalpha() or bb == b"~":
                        break
                key = {
                    b"A": "up", b"B": "down", b"C": "right", b"D": "left",
                    b"H": "home", b"F": "end",
                    b"1~": "home", b"4~": "end", b"7~": "home", b"8~": "end",
                    b"3~": "delete",
                }.get(seq, "other")
                return (key, "")
            return ("esc", "")
        # ASCII printable
        if 0x20 <= c < 0x80:
            return ("char", chr(c))
        # UTF-8 leading byte → read continuation bytes
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
    if ch == "\x01":
        return ("home", "")
    if ch == "\x05":
        return ("end", "")
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
        return ({"H": "up", "P": "down", "K": "left", "M": "right",
                 "G": "home", "O": "end", "S": "delete"}
                .get(code, "other"), "")
    # msvcrt.getwch returns a wide character (e.g. Hangul) as a single unit.
    return ("char", ch)


def _read_event() -> tuple[str, str]:
    return _read_event_windows() if os.name == "nt" else _read_event_posix()


# -- redraw ------------------------------------------------------------------

def _clear_menu(prev_lines: int) -> None:
    if prev_lines <= 0:
        return
    for _ in range(prev_lines):
        sys.stdout.write("\n\x1b[2K")
    sys.stdout.write(f"\x1b[{prev_lines}A")
    sys.stdout.flush()


def _redraw(prompt: str, buffer: str, cursor: int, menu_lines: list[str],
            prev_menu_lines: int) -> int:
    """Redraw input + dropdown. Cursor lands at the logical ``cursor`` column."""
    _clear_menu(prev_menu_lines)
    sys.stdout.write("\r\x1b[2K" + prompt + buffer)
    n = len(menu_lines)
    if n:
        # Draw menu below the input line, then come back to the input row.
        sys.stdout.write("\n")
        for i, line in enumerate(menu_lines):
            sys.stdout.write("\x1b[2K" + line)
            if i < n - 1:
                sys.stdout.write("\n")
        sys.stdout.write(f"\x1b[{n}A")
    # Final cursor position = visible(prompt) + cursor + 1 (1-indexed col).
    col = visible_len(prompt) + cursor + 1
    sys.stdout.write(f"\r\x1b[{col}G")
    sys.stdout.flush()
    return n


# -- the driver -------------------------------------------------------------

def prompt_with_completion(prompt: str,
                           commands: Sequence[CommandHint],
                           history: Optional[list[str]] = None) -> Optional[str]:
    """Read one input line with inline ``/cmd`` completion + line editing.

    ``history`` (if provided) backs the ↑/↓ history feature when the dropdown
    is inactive. Submitted lines are appended in place (caller passes the
    same list to preserve order across turns). Returns the entered string or
    ``None`` on Ctrl-C / EOF.
    """
    if not _is_interactive():
        try:
            return input(prompt)
        except (EOFError, KeyboardInterrupt):
            return None

    hist: list[str] = history if history is not None else []
    state = EditorState()
    prev_menu_lines = 0

    sys.stdout.write(prompt)
    sys.stdout.flush()

    while not state.submitted and not state.exited:
        ms = matches_for(state, commands)
        menu_lines = render_menu_lines(ms, state.selected) if ms else []
        prev_menu_lines = _redraw(prompt, state.buffer, state.cursor,
                                  menu_lines, prev_menu_lines)
        event = _read_event()
        apply_event(state, event, commands, hist)

    _clear_menu(prev_menu_lines)
    sys.stdout.write("\n")
    sys.stdout.flush()

    if state.exited:
        return None
    line = state.submitted or ""
    if line and (not hist or hist[-1] != line):
        hist.append(line)
    return line


# -- adapter for the REPL ---------------------------------------------------

def hints_from_registry(registry: dict) -> list[CommandHint]:
    """Convert ``birkin.slashcommands._REGISTRY`` into a CommandHint list."""
    out: list[CommandHint] = []
    seen: set[str] = set()
    for name, cmd in registry.items():
        if name in seen:
            continue
        seen.add(name)
        out.append(CommandHint(name=name, summary=getattr(cmd, "summary", "")))
    out.sort(key=lambda h: h.name)
    return out
