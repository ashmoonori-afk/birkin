"""Inline slash-command autocomplete + line editor for the birkin REPL.

A stdlib-only line editor that activates a live ``/cmd`` dropdown the moment
the user types ``/``. Cursor motion (←/→, Home/End), in-place deletion
(Delete in addition to Backspace), and history navigation (↑/↓ when the
dropdown is not active) are all supported.

Architecture: :class:`EditorState` plus transition functions. The pure
helpers (filter/render) return new values, while :func:`apply_event`
mutates the passed ``EditorState`` in place and returns it (a builder
pattern). Either way no transition touches I/O — only the raw-input and
redraw functions do — which keeps the bulk of behavior unit-testable
offline.

Cross-platform: POSIX termios + Windows ``msvcrt``. UTF-8 multi-byte input
is reassembled on POSIX; ``msvcrt.getwch`` returns wide characters directly
on Windows. On non-TTY stdin/stdout the function transparently falls back to
plain :func:`input` so scripts, pipes, and pytest are unaffected.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

# Lazy ANSI imports — keep this module usable even if ui.py isn't importable
# during isolated tests.
try:
    from .ui import CYAN, DIM, RESET
except Exception:  # pragma: no cover - defensive
    CYAN = DIM = RESET = ""

# Enable ANSI / VT processing. On Windows the bare ``os.system("")`` trick
# silently no-ops on some consoles (redirected stdout, legacy conhost) — and then
# the line editor's in-place redraw escape codes are emitted but ignored, so every
# keystroke drifts onto a fresh line. Actually flip the console's
# ENABLE_VIRTUAL_TERMINAL_PROCESSING flag and record whether it took, so the editor
# can fall back to plain ``input()`` when VT is unavailable.
def _enable_vt() -> bool:
    """Return True when ANSI/VT escape codes are honored by stdout."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        # Declare signatures: without restype=HANDLE the 64-bit console handle is
        # truncated to a 32-bit int (ctypes' default), yielding a bad handle so
        # SetConsoleMode silently fails and VT stays off (cursor codes ignored).
        k.GetStdHandle.restype = wintypes.HANDLE
        k.GetStdHandle.argtypes = [wintypes.DWORD]
        k.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        h = k.GetStdHandle(-11)                     # STD_OUTPUT_HANDLE
        if not h:
            return False
        mode = wintypes.DWORD()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False                            # stdout is piped, not a console
        ENABLE_VT = 0x0004                          # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        if not k.SetConsoleMode(h, mode.value | ENABLE_VT):
            return False
        k.GetConsoleMode(h, ctypes.byref(mode))
        return bool(mode.value & ENABLE_VT)
    except Exception:
        return False


_VT_OK = _enable_vt()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_HISTORY_FILENAME = "repl_history.txt"
_HISTORY_LIMIT = 500

# POSIX byte pushback used to abort a paste-batch on a control byte without
# losing it (msvcrt has built-in ``ungetwch`` so Windows doesn't need this).
_pushback: list[int] = []

# Kitty Keyboard Protocol — "disambiguate escape codes" mode (flag 1). Turning
# this on makes modifier-bearing keys (Shift+Enter, Ctrl+Enter, …) come in as
# CSI sequences such as ``\x1b[13;2u``; un-modified keys still arrive
# unchanged. Terminals that don't support the protocol silently ignore the
# enable / disable sequences.
KITTY_ENABLE = "\x1b[>1u"
KITTY_DISABLE = "\x1b[<u"

# Match Kitty-protocol "modified Enter" sequences: ``[13;<mod>u`` where
# ``<mod>`` ≥ 2 (1 means "no modifier" and we don't expect it for Enter).
# Accepts any modifier value 2..N (single digit 2-9 OR two-or-more digits)
# so future protocol extensions (mod 16 = Shift+Alt+Ctrl+Super, etc.) work.
_KITTY_MOD_ENTER_RE = re.compile(rb"^13;([2-9]|\d{2,})u$")


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
    return os.path.commonprefix(list(strings))


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


def compute_view(buffer_len: int, cursor: int,
                 content_width: int) -> tuple[int, int]:
    """Pick a horizontal-scroll window over ``buffer`` so the cursor stays
    visible. Returns ``(view_start, view_end)`` (half-open). Stateless — every
    redraw recomputes from the current cursor + width.

    Heuristic: place the cursor about 70 % into the visible window so the
    next character typed isn't immediately at the right edge.
    """
    if content_width <= 0 or buffer_len <= content_width:
        return 0, buffer_len
    target = max(0, cursor - int(content_width * 0.7))
    target = min(target, buffer_len - content_width)
    return target, target + content_width


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


def cursor_row_col(buffer: str, cursor: int) -> tuple[int, int]:
    """Return ``(row, col)`` of ``cursor`` within a possibly-multiline buffer.

    Rows are 0-indexed; ``col`` is the number of characters since the last
    ``\\n`` (or since the start if the cursor is on the first row).
    """
    before = buffer[:cursor]
    row = before.count("\n")
    last_nl = before.rfind("\n")
    col = cursor - last_nl - 1 if last_nl != -1 else cursor
    return row, col


def _move_up_line(state: EditorState) -> bool:
    """Move cursor to the previous line at (approximately) the same column.
    Returns True if it moved, False if already on the first line."""
    row, col = cursor_row_col(state.buffer, state.cursor)
    if row == 0:
        return False
    # Position of the \n that ends the previous line.
    prev_nl = state.buffer.rfind("\n", 0, state.cursor - col - 1)
    prev_start = prev_nl + 1
    prev_end = state.buffer.find("\n", prev_start)
    if prev_end == -1:
        prev_end = state.cursor - col - 1  # the current line's leading \n
    new_col = min(col, prev_end - prev_start)
    state.cursor = prev_start + new_col
    return True


def _move_down_line(state: EditorState) -> bool:
    """Symmetric to :func:`_move_up_line`."""
    row, col = cursor_row_col(state.buffer, state.cursor)
    next_nl = state.buffer.find("\n", state.cursor)
    if next_nl == -1:
        return False   # already on the last line
    next_start = next_nl + 1
    next_end = state.buffer.find("\n", next_start)
    if next_end == -1:
        next_end = len(state.buffer)
    new_col = min(col, next_end - next_start)
    state.cursor = next_start + new_col
    return True


def _prev_word(buffer: str, cursor: int) -> int:
    """Index at the start of the word before ``cursor`` (skip spaces, then word)."""
    i = cursor
    while i > 0 and buffer[i - 1].isspace():
        i -= 1
    while i > 0 and not buffer[i - 1].isspace():
        i -= 1
    return i


def _next_word(buffer: str, cursor: int) -> int:
    """Index at the end of the word after ``cursor`` (skip spaces, then word)."""
    n = len(buffer)
    i = cursor
    while i < n and buffer[i].isspace():
        i += 1
    while i < n and not buffer[i].isspace():
        i += 1
    return i


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

    if kind == "newline":
        # Multi-line insert: like ``char`` but always a literal ``\n``. Submit
        # is bound to ``enter`` (\r) only — the two are deliberately split.
        state.buffer = state.buffer[:state.cursor] + "\n" + state.buffer[state.cursor:]
        state.cursor += 1
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
    if kind == "word_left":
        state.cursor = _prev_word(state.buffer, state.cursor)
        return state
    if kind == "word_right":
        state.cursor = _next_word(state.buffer, state.cursor)
        return state
    if kind == "delete_word":   # Ctrl-W — delete the word before the cursor
        start = _prev_word(state.buffer, state.cursor)
        if start < state.cursor:
            state.buffer = state.buffer[:start] + state.buffer[state.cursor:]
            state.cursor = start
            state.selected = 0
            state.menu_dismissed = False
            state.history_idx = -1
            state.pending = None
        return state
    if kind == "kill_to_start":  # Ctrl-U — delete to the CURRENT line's start
        line_start = state.buffer.rfind("\n", 0, state.cursor) + 1  # 0 if none
        if line_start < state.cursor:
            state.buffer = state.buffer[:line_start] + state.buffer[state.cursor:]
            state.cursor = line_start
            state.selected = 0
            state.menu_dismissed = False
            state.history_idx = -1
            state.pending = None
        return state
    if kind == "kill_to_end":    # Ctrl-K — delete to the CURRENT line's end
        line_end = state.buffer.find("\n", state.cursor)
        if line_end == -1:
            line_end = len(state.buffer)
        if state.cursor < line_end:
            state.buffer = state.buffer[:state.cursor] + state.buffer[line_end:]
            state.selected = 0
            state.menu_dismissed = False
            state.history_idx = -1
            state.pending = None
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
        elif "\n" in state.buffer:
            # In multi-line mode ↑ moves the cursor between lines; history is
            # reserved for single-line input so a half-typed multi-line draft
            # can never be lost to an accidental ↑.
            _move_up_line(state)
        else:
            _history_prev(state, history)
        return state

    if kind == "down":
        ms = matches_for(state, commands)
        if ms:
            state.selected = (state.selected + 1) % len(ms)
        elif "\n" in state.buffer:
            _move_down_line(state)
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
    """One key read on POSIX, including CSI sequences for navigation keys.

    Printable runs (typed sequences, large pastes) are coalesced into a single
    ``("char", text)`` event by greedily draining the OS buffer with a
    zero-timeout ``select`` until a control byte appears. The first control
    byte aborts the batch and is pushed back so the next call sees it.
    """
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)

        # Honor any pushed-back control byte from a previous paste batch.
        if _pushback:
            c = _pushback.pop(0)
        else:
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
        if c == 0x0d:
            return ("enter", "")
        if c == 0x0a:
            # Ctrl-J — multiline newline insertion (Enter is \r, see above).
            return ("newline", "")
        if c == 0x09:
            return ("tab", "")
        if c == 0x17:   # Ctrl-W
            return ("delete_word", "")
        if c == 0x15:   # Ctrl-U
            return ("kill_to_start", "")
        if c == 0x0b:   # Ctrl-K
            return ("kill_to_end", "")
        if c in (0x7f, 0x08):
            return ("backspace", "")
        if c == 0x1b:
            # CSI / SS3 sequence? Read more non-blockingly. If nothing
            # follows within ~30ms it's a bare Esc.
            ready, _, _ = select.select([fd], [], [], 0.03)
            if not ready:
                return ("esc", "")
            nb = os.read(fd, 1)
            if nb in (b"\r", b"\n"):
                # Alt+Enter is commonly emitted as ESC + \r or ESC + \n —
                # treat it as the multiline-newline trigger.
                return ("newline", "")
            if nb in (b"b", b"B"):   # Alt+B — word left
                return ("word_left", "")
            if nb in (b"f", b"F"):   # Alt+F — word right
                return ("word_right", "")
            if nb in (b"[", b"O"):
                seq = b""
                # Read until terminator (alpha letter or '~') or no more data.
                # Bumped to 16 bytes to fit Kitty-protocol sequences such as
                # ``13;2u`` (Shift+Enter) and friends.
                for _ in range(16):
                    rdy, _, _ = select.select([fd], [], [], 0.03)
                    if not rdy:
                        break
                    bb = os.read(fd, 1)
                    seq += bb
                    if bb.isalpha() or bb == b"~":
                        break
                # Kitty Keyboard Protocol: modified Enter (Shift / Alt / Ctrl
                # / any combination) arrives as ``[13;<mod>u``. Map all of
                # them to the multiline newline trigger so Shift+Enter feels
                # natural on terminals that support the protocol.
                if _KITTY_MOD_ENTER_RE.match(seq):
                    return ("newline", "")
                # Modified arrows (Ctrl/Alt+←/→) arrive as e.g. ``1;5C`` / ``1;3D``
                # — jump by word. The bare arrows (``C``/``D``) fall through below.
                if b";" in seq and seq.endswith(b"C"):
                    return ("word_right", "")
                if b";" in seq and seq.endswith(b"D"):
                    return ("word_left", "")
                key = {
                    b"A": "up", b"B": "down", b"C": "right", b"D": "left",
                    b"H": "home", b"F": "end",
                    b"1~": "home", b"4~": "end", b"7~": "home", b"8~": "end",
                    b"3~": "delete",
                }.get(seq, "other")
                return (key, "")
            return ("esc", "")
        # Printable / UTF-8: start a paste-batch.
        chunk = bytearray()
        if 0x20 <= c < 0x80:
            chunk.append(c)
        else:
            # UTF-8 leading byte → consume continuation bytes
            if c & 0xE0 == 0xC0:
                extra = 1
            elif c & 0xF0 == 0xE0:
                extra = 2
            elif c & 0xF8 == 0xF0:
                extra = 3
            else:
                return ("other", "")
            chunk.append(c)
            rest = os.read(fd, extra)
            chunk.extend(rest)

        # Greedily drain anything else immediately available — stop on a
        # control byte (and push it back so the next call handles it). This
        # is what turns a 5000-char paste into a single redraw.
        #
        # Newlines (``\n``, 0x0a) and tabs (``\t``, 0x09) ARE kept inside the
        # batch — a paste of a code snippet or a multi-line block should land
        # in the buffer verbatim. Carriage-return (``\r``, 0x0d) still aborts
        # the batch because it's the "submit" signal.
        while True:
            rdy, _, _ = select.select([fd], [], [], 0)
            if not rdy:
                break
            nb = os.read(fd, 1)
            if not nb:
                break
            nc = nb[0]
            if nc in (0x09, 0x0a):
                chunk.append(nc)
                continue
            if nc < 0x20 or nc == 0x7f or nc == 0x1b:
                _pushback.append(nc)
                break
            chunk.append(nc)
        try:
            return ("char", bytes(chunk).decode("utf-8", errors="replace"))
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
    if ch == "\r":
        return ("enter", "")
    if ch == "\n":
        return ("newline", "")   # Ctrl-J on Windows
    if ch == "\t":
        return ("tab", "")
    if ch == "\x17":   # Ctrl-W
        return ("delete_word", "")
    if ch == "\x15":   # Ctrl-U
        return ("kill_to_start", "")
    if ch == "\x0b":   # Ctrl-K
        return ("kill_to_end", "")
    if ch == "\x08":
        return ("backspace", "")
    if ch == "\x1b":
        return ("esc", "")
    if ch in ("\x00", "\xe0"):
        code = msvcrt.getwch()
        return ({"H": "up", "P": "down", "K": "left", "M": "right",
                 "G": "home", "O": "end", "S": "delete",
                 "s": "word_left", "t": "word_right"}  # Ctrl+←/Ctrl+→
                .get(code, "other"), "")
    # Paste batch: drain anything immediately queued (printable + \n + \t).
    # On a control char we push it back via ``ungetwch`` so the next call
    # sees it — same idea as the POSIX pushback list. ``\r`` (Enter / submit)
    # always aborts the batch; ``\n`` and ``\t`` are kept verbatim so pasted
    # multi-line content lands in the buffer as typed.
    text = ch
    while msvcrt.kbhit():
        nxt = msvcrt.getwch()
        if nxt in ("\x00", "\xe0"):
            msvcrt.ungetwch(nxt)
            break
        if nxt == "\r" or nxt == "\x7f":
            msvcrt.ungetwch(nxt)
            break
        if ord(nxt) < 0x20 and nxt not in ("\t", "\n"):
            msvcrt.ungetwch(nxt)
            break
        text += nxt
    return ("char", text)


def _read_event() -> tuple[str, str]:
    return _read_event_windows() if os.name == "nt" else _read_event_posix()


# -- redraw ------------------------------------------------------------------

def _terminal_cols() -> int:
    """Best-effort terminal width (defaults to 80)."""
    import shutil
    try:
        return max(20, shutil.get_terminal_size((80, 24)).columns)
    except Exception:
        return 80


def _redraw(prompt: str, buffer: str, cursor: int, menu_lines: list[str],
            prev_cursor_row: int, prev_total_rows: int) -> tuple[int, int]:
    """Redraw a (possibly multi-line) input + dropdown.

    The buffer is split on ``\\n``; each logical line is drawn on its own
    screen row. The first row carries the ``prompt``; subsequent rows are
    indented by ``visible_len(prompt)`` spaces so the wrapped text aligns.
    Per-row horizontal scrolling is applied with the same ``compute_view``
    rule used in single-line mode. The dropdown is drawn below the last
    input row, and the cursor finally lands at its logical ``(row, col)``.

    Returns ``(new_cursor_row, new_total_rows)`` so the *next* redraw can
    walk back up to the input anchor and overwrite cleanly.
    """
    # 1. Walk back to the anchor (first input row, column 0) and clear every
    #    row we drew last time.
    if prev_cursor_row > 0:
        sys.stdout.write(f"\x1b[{prev_cursor_row}A")
    sys.stdout.write("\r")
    for i in range(max(prev_total_rows, 1)):
        sys.stdout.write("\x1b[2K")
        if i < prev_total_rows - 1:
            sys.stdout.write("\n")
    if prev_total_rows > 1:
        sys.stdout.write(f"\x1b[{prev_total_rows - 1}A")
    sys.stdout.write("\r")

    # 2. Render input lines.
    cols = _terminal_cols()
    prompt_w = visible_len(prompt)
    content_w = max(10, cols - prompt_w - 4)
    indent = " " * prompt_w

    cur_row, cur_col = cursor_row_col(buffer, cursor)
    lines = buffer.split("\n")
    line_views: list[tuple[int, int]] = []   # (view_start, left_marker_len) per row
    for i, ln in enumerate(lines):
        if i == cur_row:
            vs, ve = compute_view(len(ln), cur_col, content_w)
        else:
            vs, ve = 0, min(len(ln), content_w)
        left = "…" if vs > 0 else ""
        right = "…" if ve < len(ln) else ""
        line_views.append((vs, len(left)))
        prefix = prompt if i == 0 else indent
        sys.stdout.write(prefix + left + ln[vs:ve] + right)
        if i < len(lines) - 1:
            sys.stdout.write("\n")

    # 3. Dropdown rows, if any.
    n_input = len(lines)
    n_menu = len(menu_lines)
    if n_menu:
        sys.stdout.write("\n")
        for j, mline in enumerate(menu_lines):
            sys.stdout.write("\x1b[2K" + mline)
            if j < n_menu - 1:
                sys.stdout.write("\n")

    new_total_rows = n_input + n_menu

    # 4. Park the cursor at its logical (row, col). We're currently at the end
    #    of the very last drawn row.
    rows_below_cursor = (n_input - 1 - cur_row) + n_menu
    if rows_below_cursor > 0:
        sys.stdout.write(f"\x1b[{rows_below_cursor}A")
    vs, left_len = line_views[cur_row]
    cur_visual_col = prompt_w + left_len + (cur_col - vs) + 1
    sys.stdout.write(f"\r\x1b[{cur_visual_col}G")
    sys.stdout.flush()
    return cur_row, new_total_rows


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
    if not _is_interactive() or not _VT_OK:
        # No real TTY, or the console can't do VT redraws — use plain input()
        # so typing isn't broken into one char per line.
        try:
            return input(prompt)
        except (EOFError, KeyboardInterrupt):
            return None

    hist: list[str] = history if history is not None else []
    state = EditorState()
    # Drop any control byte a *previous* prompt pushed back (e.g. a paste that
    # ended on Ctrl-C) so it can't fire into this fresh session.
    _pushback.clear()
    # Track of where we drew last (relative to the anchor row) so the next
    # redraw can step back up and overwrite cleanly.
    prev_cursor_row = 0
    prev_total_rows = 1

    # Opt in to the Kitty Keyboard Protocol so Shift/Ctrl/Alt+Enter come in
    # as distinguishable CSI sequences. Terminals that don't support it just
    # ignore the enable byte — there is no fallback to manage.
    sys.stdout.write(KITTY_ENABLE)
    sys.stdout.write(prompt)
    sys.stdout.flush()

    try:
        while not state.submitted and not state.exited:
            ms = matches_for(state, commands)
            menu_lines = render_menu_lines(ms, state.selected) if ms else []
            prev_cursor_row, prev_total_rows = _redraw(
                prompt, state.buffer, state.cursor, menu_lines,
                prev_cursor_row, prev_total_rows)
            event = _read_event()
            apply_event(state, event, commands, hist)
    finally:
        # Always restore, even if the loop raised: park the cursor below all
        # rendered rows, emit a clean newline, and disable the Kitty Keyboard
        # Protocol so a leftover enable can't confuse the shell or other apps.
        rows_below = prev_total_rows - 1 - prev_cursor_row
        if rows_below > 0:
            sys.stdout.write(f"\x1b[{rows_below}B")
        sys.stdout.write("\n")
        sys.stdout.write(KITTY_DISABLE)
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
    out = [CommandHint(name=name, summary=getattr(cmd, "summary", ""))
           for name, cmd in registry.items()]
    out.sort(key=lambda h: h.name)
    return out
