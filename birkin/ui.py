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
        # No animation in plain/piped/CI mode — a braille spinner streamed to a
        # file or a screen reader is noise. The turn still runs; it's just quiet.
        if plain_mode():
            return
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
            # Memory tools get a visible, non-dim line: the user should SEE
            # what was remembered/recalled (P1-2).
            if not payload.get("is_error"):
                from .memory import memory_activity_line
                line = memory_activity_line(payload.get("name", ""),
                                            payload.get("content", "") or "")
                if line:
                    sys.stdout.write(f"  {CYAN}{line}{RESET}\n")
        elif event == "compact":
            sys.stdout.write(
                f"\n{DIM}  ⤵ compacted context ({payload.get('reason')}): "
                f"{payload.get('before')} → {payload.get('after')} messages"
                f"{RESET}\n")
        elif event == "subagent.start":
            sys.stdout.write(f"\n{DIM}  ⇲ subagent: {payload.get('task', '')}{RESET}\n")
        elif event == "subagent.done":
            sys.stdout.write(f"{DIM}  ⇱ subagent done{RESET}\n")
        sys.stdout.flush()
    return emit
