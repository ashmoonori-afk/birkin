"""Shared terminal UI helpers (ANSI styling, streaming, tool-event printer).

Kept separate so both the REPL and the slash-command handlers render
identically without importing each other.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import sys
import threading
from typing import Any, Callable


def should_color(stream: Any = None) -> bool:
    """Whether to emit ANSI SGR/animation. Single choke-point.

    Priority chain fixed by the NO_COLOR spec, CLICOLOR_FORCE (bixense) and
    clig.dev — getting the order wrong (especially "empty vs set" and
    "FORCE vs TTY") is the #1 CLI color bug:
      1. NO_COLOR / BIRKIN_NO_COLOR set & non-empty -> off (absolute)
      2. CLICOLOR_FORCE non-empty                   -> on (even non-TTY)
      3. stdout is a TTY and TERM != dumb           -> on
      4. otherwise (pipe, CI, redirect)             -> off
    An empty value ("") is treated as unset, per spec, because
    ``os.environ.get`` returns a falsy empty string.
    """
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("BIRKIN_NO_COLOR"):
        return False
    if os.environ.get("CLICOLOR_FORCE"):
        return True
    try:
        tty = stream.isatty()
    except Exception:
        tty = False
    return bool(tty) and os.environ.get("TERM") != "dumb"


def plain_mode() -> bool:
    """Reduced-motion / screen-reader mode: no animation, static tokens.

    Implied whenever color is off (pipe/CI), or forced with BIRKIN_PLAIN so a
    screen-reader user keeps color but drops the spinner. See clig.dev
    "don't animate unless stdout is an interactive terminal"."""
    return bool(os.environ.get("BIRKIN_PLAIN")) or not should_color()


# Palette — every SGR passes through the gate once, so a piped/CI/NO_COLOR run
# emits no escapes at all and ``f"{RED}✗{RESET}"`` degrades to a bare ``✗``
# (glyphs/labels always carry the meaning; color only reinforces it).
_C = should_color()
DIM = "\033[2m" if _C else ""
BOLD = "\033[1m" if _C else ""
CYAN = "\033[36m" if _C else ""
GREEN = "\033[32m" if _C else ""
YELLOW = "\033[33m" if _C else ""
RED = "\033[31m" if _C else ""
UNDERLINE = "\033[4m" if _C else ""
RESET = "\033[0m" if _C else ""


BIRKIN_ART = [
    " ██████╗ ██╗██████╗ ██╗  ██╗██╗███╗   ██╗",
    " ██╔══██╗██║██╔══██╗██║ ██╔╝██║████╗  ██║",
    " ██████╔╝██║██████╔╝█████╔╝ ██║██╔██╗ ██║",
    " ██╔══██╗██║██╔══██╗██╔═██╗ ██║██║╚██╗██║",
    " ██████╔╝██║██║  ██║██║  ██╗██║██║ ╚████║",
    " ╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝",
]
BIRKIN_BANNER = "\n" + "\n".join(BIRKIN_ART)


def stream_text(piece: str) -> None:
    sys.stdout.write(piece)
    sys.stdout.flush()


# -- display width (CJK-aware) ---------------------------------------------
#
# The load-bearing primitive for every alignment: columns, gauges, box edges,
# and truncation must count *display cells*, not bytes or code points. Hangul
# (U+AC00–D7A3) is East-Asian Wide = 2 cells, so ``len()`` tears every box in a
# Korean-first app. stdlib ``unicodedata.east_asian_width`` already ships the
# UAX#11 table, so no wcwidth port is needed.
#
# Caveats (per the plan's adversarial review): the Unicode table tracks the
# running Python version, and emoji width (VS16 / ZWJ / regional indicators) is
# not composed — harmless for Hangul, approximate for emoji in tool output.
# Ambiguous width is mapped to 1 (modern terminals); a Wide-ambiguous terminal
# needs the override below.
import unicodedata  # noqa: E402

# ANSI CSI sequences (colors, cursor moves) occupy zero display cells.
_ANSI_RE = re.compile(r"\033\[[0-9;?]*[ -/]*[@-~]")


def cell_width(s: str, *, ambiguous_wide: bool = False) -> int:
    """Display width of ``s`` in terminal cells, ignoring ANSI escapes."""
    s = _ANSI_RE.sub("", s)
    w = 0
    for ch in s:
        if unicodedata.combining(ch) or unicodedata.category(ch) in (
                "Mn", "Me", "Cf"):
            continue                       # combining / zero-width marks
        eaw = unicodedata.east_asian_width(ch)
        if eaw in ("W", "F"):
            w += 2
        elif eaw == "A":
            w += 2 if ambiguous_wide else 1
        else:
            w += 1
    return w


def fit(s: str, width: int, *, marker: str = "…",
        ambiguous_wide: bool = False) -> str:
    """Truncate ``s`` to at most ``width`` display cells, adding ``marker``.

    Never splits inside a wide glyph. Returns ``s`` unchanged when it fits.
    """
    if width <= 0:
        return ""
    if cell_width(s, ambiguous_wide=ambiguous_wide) <= width:
        return s
    mw = cell_width(marker, ambiguous_wide=ambiguous_wide)
    budget = max(0, width - mw)
    out, used = [], 0
    for ch in s:
        cw = cell_width(ch, ambiguous_wide=ambiguous_wide)
        if used + cw > budget:
            break
        out.append(ch)
        used += cw
    return "".join(out) + marker


def pad(s: str, width: int, *, align: str = "left",
        ambiguous_wide: bool = False) -> str:
    """Pad ``s`` with spaces to exactly ``width`` display cells (or fit if over).

    ``align`` is ``left`` or ``right``. Uses display width so a column of
    mixed Hangul/ASCII lines up.
    """
    s = fit(s, width, ambiguous_wide=ambiguous_wide)
    gap = width - cell_width(s, ambiguous_wide=ambiguous_wide)
    if gap <= 0:
        return s
    return (" " * gap + s) if align == "right" else (s + " " * gap)


# -- gauges / sparklines / severity ----------------------------------------
#
# Pure-ANSI primitives that return strings, so they drop straight into a
# line-flow status line or a /dash cell (a sparkline is the only line-flow-safe
# time series — no fixed 2D plot region). Block glyphs are the default: btop and
# bottom both warn braille "renders as broken boxes without font setup", and
# birkin is Windows + CJK first, so braille width/coverage is unreliable.

_SPARK = "▁▂▃▄▅▆▇█"          # U+2581..2588, 8 levels


def bar(frac: float, width: int = 8) -> str:
    """Horizontal fill meter, e.g. ``██████░░``. Empty track is ``░`` (not a
    space) so it stays visible on any background (htop)."""
    frac = 0.0 if frac != frac else max(0.0, min(1.0, frac))  # clamp; NaN->0
    fill = round(frac * width)
    return "█" * fill + "░" * (width - fill)


def spark(series: list[float]) -> str:
    """Block sparkline of a series compressed to one glyph per point (btop)."""
    if not series:
        return ""
    lo, hi = min(series), max(series)
    span = (hi - lo) or 1.0
    return "".join(_SPARK[min(7, int((v - lo) / span * 7))] for v in series)


def severity(value: float, careful: float, warning: float,
             critical: float) -> str:
    """Map a value to a semantic color by threshold (glances careful/warn/crit).

    Thresholds are passed in, never hard-coded — a user's budget caps and
    "stale" windows differ, so callers read them from config.
    """
    if value >= critical:
        return RED
    if value >= warning:
        return YELLOW
    if value >= careful:
        return GREEN
    return DIM


# -- markdown -> ANSI ------------------------------------------------------

_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC_RE = re.compile(r"(?<![\*\w])\*([^*\n]+?)\*(?![\*\w])")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUM_RE = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")
_RULE_RE = re.compile(r"^(---+|\*\*\*+|___+)$")
_RULE = DIM + "─" * 48 + RESET


def _inline(s: str) -> str:
    s = _LINK_RE.sub(lambda m: f"{UNDERLINE}{m.group(1)}{RESET} {DIM}{m.group(2)}{RESET}", s)
    s = _CODE_RE.sub(lambda m: f"{CYAN}{m.group(1)}{RESET}", s)
    s = _BOLD_RE.sub(lambda m: f"{BOLD}{m.group(1) or m.group(2)}{RESET}", s)
    s = _ITALIC_RE.sub(lambda m: f"{UNDERLINE}{m.group(1)}{RESET}", s)
    return s


def render_markdown(text: str) -> str:
    """Render a subset of Markdown to ANSI for the terminal. Best-effort:
    headers, bold/italic, inline code, links, bullets, numbered lists, rules,
    and fenced code blocks. Falls back to the raw text on any error."""
    try:
        out: list[str] = []
        in_code = False
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code = not in_code
                out.append(_RULE)
                continue
            if in_code:
                out.append(f"{DIM}  {line}{RESET}")
                continue
            if _RULE_RE.match(stripped):
                out.append(_RULE)
                continue
            h = _HEADER_RE.match(line)
            if h:
                out.append(f"{BOLD}{CYAN}{h.group(2)}{RESET}")
                continue
            b = _BULLET_RE.match(line)
            if b:
                out.append(f"{b.group(1)}{CYAN}•{RESET} {_inline(b.group(2))}")
                continue
            n = _NUM_RE.match(line)
            if n:
                out.append(f"{n.group(1)}{CYAN}{n.group(2)}.{RESET} {_inline(n.group(3))}")
                continue
            out.append(_inline(line))
        return "\n".join(out)
    except Exception:
        return text


_CLEAR_EOL = "\033[K"          # CSI 0K — erase to end of line, width-independent


class Spinner:
    """A 'thinking…' indicator: braille frame + elapsed seconds + an interrupt
    hint. The hint is not a lie — birkin's abortkey listener makes Esc actually
    interrupt and a typed line actually steer.

    Runs in a daemon thread; ``stop()`` clears the line. Safe to stop twice.
    Inert in plain/piped mode (see ``start``).
    """

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label: str = "thinking…",
                 hint: str = "esc 중단 · 입력 후 Enter=조종"):
        self.label = label
        self.hint = hint
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0 = 0.0

    def start(self) -> None:
        # No animation in plain/piped/CI mode — a braille spinner streamed to a
        # file or a screen reader is noise. The turn still runs; it's just quiet.
        if plain_mode():
            return
        import time
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        import time
        for frame in itertools.cycle(self._FRAMES):
            if self._stop.wait(0.09):
                break
            elapsed = int(time.monotonic() - self._t0)
            tail = f" · {DIM}{self.hint}{RESET}" if self.hint else ""
            # \r to column 0, draw, then \033[K wipes any leftover tail from a
            # previously longer line — width-independent, unlike padding spaces.
            sys.stdout.write(
                f"\r{DIM}{frame} {self.label} {elapsed}s{RESET}{tail}{_CLEAR_EOL}")
            sys.stdout.flush()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=0.3)
        self._thread = None
        # Erase the whole live line regardless of its (variable) width.
        sys.stdout.write("\r" + _CLEAR_EOL)
        sys.stdout.flush()


def hint(*parts: str) -> None:
    """Print a DIM one-line key/action hint at the moment a choice is offered.

    The line-flow translation of lazygit/gitui's contextual key bar: no box, no
    cursor move, no scroll region — just an appended line, so it needs no width
    math (nothing to the right to align). Silent when color is off would hide
    the guidance, so it prints plainly (the text still helps a piped reader).
    """
    if not parts:
        return
    body = f"{DIM} · {RESET}".join(parts)
    sys.stdout.write(f"  {DIM}{body}{RESET}\n")
    sys.stdout.flush()


# /details toggles verbose tool traces (full input + a result snippet).
# opencode's /details; a module flag so the /details command and the per-session
# printer share one switch without threading cfg through.
_DETAILS = {"on": False}


def set_details(on: bool) -> bool:
    _DETAILS["on"] = bool(on)
    return _DETAILS["on"]


def details_on() -> bool:
    return _DETAILS["on"]


def make_event_printer() -> Callable[[str, dict[str, Any]], None]:
    """Return an on_event callback that prints tool activity as an indented,
    timed trace tree. subagent.start/done nest the depth; each tool shows its
    own elapsed time.
    """
    import time
    state: dict[str, Any] = {"depth": 0, "t0": {}}   # id/name -> start time

    def _pad() -> str:
        return "  " + "  " * state["depth"]

    def _key(payload: dict[str, Any]) -> str:
        return str(payload.get("id") or payload.get("name") or "")

    def emit(event: str, payload: dict[str, Any]) -> None:
        pad = _pad()
        if event == "tool_start":
            state["t0"][_key(payload)] = time.monotonic()
            inp = json.dumps(payload.get("input", {}), ensure_ascii=False)
            cap = 200 if _DETAILS["on"] else 80
            if len(inp) > cap:
                inp = inp[:cap] + "…"
            sys.stdout.write(f"\n{DIM}{pad}→ {payload.get('name')} {inp}{RESET}\n")
        elif event == "tool_end":
            t0 = state["t0"].pop(_key(payload), None)
            dt = f" · {time.monotonic() - t0:.1f}s" if t0 else ""
            mark = (f"{RED}✗{RESET}" if payload.get("is_error")
                    else f"{GREEN}✓{RESET}")
            sys.stdout.write(f"{DIM}{pad}{mark} {payload.get('name')}{dt}{RESET}\n")
            content = payload.get("content", "") or ""
            if not payload.get("is_error"):
                # Memory tools get a visible, non-dim line (P1-2).
                from .memory import memory_activity_line
                line = memory_activity_line(payload.get("name", ""), content)
                if line:
                    sys.stdout.write(f"{pad}{CYAN}{line}{RESET}\n")
            if _DETAILS["on"] and content:
                snippet = content.strip().replace("\n", " ")[:200]
                sys.stdout.write(f"{DIM}{pad}  ↳ {snippet}{RESET}\n")
        elif event == "compact":
            sys.stdout.write(
                f"\n{DIM}{pad}⤵ compacted context ({payload.get('reason')}): "
                f"{payload.get('before')} → {payload.get('after')} messages"
                f"{RESET}\n")
        elif event == "subagent.start":
            sys.stdout.write(
                f"\n{DIM}{pad}⇲ subagent: {payload.get('task', '')}{RESET}\n")
            state["depth"] += 1
        elif event == "subagent.done":
            state["depth"] = max(0, state["depth"] - 1)
            sys.stdout.write(f"{DIM}{_pad()}⇱ subagent done{RESET}\n")
        elif event == "checkpoint":
            # Teach /undo the moment there's something to undo (lazygit shows
            # the commit key right after you stage). Was silent before.
            sys.stdout.write(
                f"{DIM}{pad}checkpoint 저장됨 · /undo 로 되돌리기{RESET}\n")
        elif event == "steer":
            said = str(payload.get("text", "") or "")[:60]
            sys.stdout.write(f"{DIM}{pad}steer 반영: {said}{RESET}\n")
        sys.stdout.flush()
    return emit
