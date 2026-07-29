"""``/dash`` — a full-screen mission-control view.

This is the one place birkin leaves line-flow: the conversation REPL rejects
pinned bars, panes and cursor tricks because they fight the scrollback, but
``/dash`` enters the alternate screen buffer and owns the whole viewport, so
those patterns become legitimate (the plan scopes them here only).

Design invariants (docs/tui-redesign-plan.md §/dash):
- Pure ANSI + stdlib. No curses/framework.
- Enter with ``?1049h`` (saves the main screen + scrollback), restore with a
  three-fold defence (try/finally + atexit + KeyboardInterrupt) so a crash
  never leaves the terminal in the alt buffer with a hidden cursor.
- Repaint by HOME + overwrite + clear-to-EOL wrapped in synchronized output
  (``?2026``); never ``2J`` (which flickers and eats scrollback).
- Every column/edge goes through ui.cell_width/fit/pad — Hangul is width 2.
- Non-TTY -> refuse the escapes and dump the same data as text/JSON.

The data snapshot and the renderer are pure functions so they can be dogfooded
without a terminal; only ``run`` touches escapes and the keyboard.
"""

from __future__ import annotations

import atexit
import os
import sys
import time
from typing import Any

from . import ui

ALT_ON, ALT_OFF = "\033[?1049h", "\033[?1049l"
HIDE, SHOW = "\033[?25l", "\033[?25h"
SYNC_ON, SYNC_OFF = "\033[?2026h", "\033[?2026l"
HOME, EL, RST = "\033[H", "\033[0K", "\033[0m"

SECTIONS = ("세션", "크론", "승인", "기억")
_RAIL_W = 14
_REFRESH_S = 2.0
_CHROME_H = 5        # 헤더 2줄 + 구분선 + 빈 줄 + 힌트 줄


# -- data snapshot (pure) --------------------------------------------------

def _human_age(iso: Any) -> str:
    from datetime import datetime, timezone
    try:
        t = datetime.fromisoformat(str(iso))
    except (ValueError, TypeError):
        return ""
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - t).total_seconds()
    if secs < 0:
        secs = 0
    if secs < 3600:
        return f"{int(secs / 60)}분전"
    if secs < 86400:
        return f"{int(secs / 3600)}시간전"
    return f"{int(secs / 86400)}일전"


def _mtime_age(path) -> str:
    try:
        from datetime import datetime, timezone
        ts = os.path.getmtime(path)
        return _human_age(datetime.fromtimestamp(ts, timezone.utc).isoformat())
    except OSError:
        return ""


def snapshot(session: Any) -> dict[str, Any]:
    """Gather every pane's data from the live backend. No escapes, testable."""
    cfg = getattr(session, "cfg", {}) or {}
    snap: dict[str, Any] = {"cfg": cfg, "header": {}, "sessions": [],
                            "cron": [], "approvals": [], "zones": [],
                            "errors": {}}

    # header: identity + budget + daemon
    h = snap["header"]
    h["model"] = cfg.get("model") or "?"
    h["provider"] = cfg.get("provider") or "?"
    try:
        from . import store
        st = store.read_status()
        h["daemon_up"] = bool(st.get("daemon")) and not store.is_status_stale(st)
        h["daemon_known"] = bool(st.get("daemon") or st.get("heartbeat"))
        h["daemon_stale"] = store.is_status_stale(st)
        from .statusline import _hhmm
        h["morpheus"] = _hhmm(st.get("next_morpheus") or st.get("next_nightly"))
    except Exception:
        h.update(daemon_up=False, daemon_known=False, daemon_stale=False,
                 morpheus="")
    try:
        from . import budget
        h["budget"] = budget.status(cfg)
    except Exception:
        h["budget"] = {}

    # sessions (non-auto transcripts, newest first)
    try:
        from . import config, transcripts
        files = [f for f in config.sessions_dir().glob("*.json")
                 if not transcripts.is_auto(f.stem)]
        files.sort(key=lambda f: f.stat().st_mtime if f.exists() else 0,
                   reverse=True)
        snap["sessions"] = [{"title": f.stem, "age": _mtime_age(f),
                             "path": str(f)} for f in files]
    except Exception as exc:
        snap["errors"]["세션"] = str(exc) or type(exc).__name__

    # cron jobs
    try:
        from . import cron
        for j in cron.load_jobs():
            snap["cron"].append({
                "name": j.get("name", "?"),
                "schedule": cron.schedule_display(j),
                "next": (j.get("next_run") or "")[:16].replace("T", " "),
                "enabled": j.get("enabled", True),
                "id": j.get("id"),
            })
    except Exception as exc:
        snap["errors"]["크론"] = str(exc) or type(exc).__name__

    # pending approvals
    try:
        from . import approvals
        for a in approvals.reviewable_pending():
            snap["approvals"].append({
                "id": a.get("id"), "category": a.get("category", "?"),
                "title": a.get("title", ""), "status": a.get("status", ""),
            })
    except Exception as exc:
        snap["errors"]["승인"] = str(exc) or type(exc).__name__

    # memory zones (aggregate)
    try:
        from .memory import Memory
        counts: dict[str, int] = {}
        for n in Memory(cfg).list_notes():
            z = n.get("zone") or "inbox"
            counts[z] = counts.get(z, 0) + 1
        snap["zones"] = [{"zone": z, "count": c}
                         for z, c in sorted(counts.items(),
                                            key=lambda kv: -kv[1])]
    except Exception as exc:
        snap["errors"]["기억"] = str(exc) or type(exc).__name__

    return snap


def _rows(snap: dict[str, Any], section: str) -> list[dict[str, Any]]:
    return {"세션": snap["sessions"], "크론": snap["cron"],
            "승인": snap["approvals"], "기억": snap["zones"]}[section]


def _counts(snap: dict[str, Any]) -> dict[str, int]:
    return {s: len(_rows(snap, s)) for s in SECTIONS}


# -- rendering (pure) ------------------------------------------------------

def _body_h(rows_h: int) -> int:
    """Body lines between the header block and the hint line.

    render() and the input loop have to agree on this. They used to differ by
    one, which let the cursor sit on a row that was never painted.
    """
    return max(3, rows_h - _CHROME_H)


def _row_capacity(height: int, n_rows: int, extra: int = 0) -> int:
    """Data rows that fit in a body slot `height` lines tall.

    _table_lines always spends one line on the column header, and one more on
    the "더 있음" indicator when it cannot show everything — so the slot height
    is never the row count. Getting this wrong truncated the indicator itself,
    which is the one line that says the list continues.
    """
    avail = max(1, height - 1 - extra)               # column header + extra
    return max(1, avail - 1) if n_rows > avail else avail


def _k(n: int) -> str:
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def _header_lines(snap: dict[str, Any], width: int) -> list[str]:
    C, D, G, Y, R, RST_ = ui.CYAN, ui.DIM, ui.GREEN, ui.YELLOW, ui.RED, ui.RESET
    h = snap["header"]
    segs = [f"{C}{ui.fit(str(h['model']), 22)}{RST_}{D}·{h['provider']}{RST_}"]
    if h.get("daemon_known"):
        if h.get("daemon_up"):
            segs.append(f"{G}●up{RST_}")
        elif h.get("daemon_stale"):
            segs.append(f"{Y}◐stale{RST_}")
        else:
            segs.append(f"{D}○down{RST_}")
    if h.get("morpheus"):
        segs.append(f"{D}morpheus {h['morpheus']}{RST_}")
    b = h.get("budget") or {}
    cap = int(b.get("daily_cap") or 0)
    used = int(b.get("used_today") or 0)
    if cap > 0:
        frac = used / cap
        col = R if b.get("over_daily") else ui.severity(frac, 0.0, 0.8, 1.0)
        segs.append(f"{col}tok {_k(used)}/{_k(cap)} {ui.bar(frac, 8)}{RST_}")
    elif used > 0:
        segs.append(f"{D}tok {_k(used)}{RST_}")
    title = f"{ui.BOLD}birkin{RST_}{D} · mission control{RST_}"
    seg_line = f"{D} · {RST_}".join(segs)
    if ui.cell_width(seg_line) > width:
        seg_line = ui.fit(seg_line, width) + RST_
    return [ui.fit(title, width), seg_line]


def _table_lines(snap: dict[str, Any], section: str, cursor: int,
                 top: int, height: int, tw: int) -> list[str]:
    C, D, RST_, INV = ui.CYAN, ui.DIM, ui.RESET, "\033[7m" if ui.CYAN else ""
    rows = _rows(snap, section)
    out: list[str] = []

    # column spec per section (label, key, width, align)
    if section == "세션":
        cols = [("대화", "title", tw - 12, "left"), ("수정", "age", 10, "left")]
    elif section == "크론":
        cols = [("이름", "name", 14, "left"), ("스케줄", "schedule", tw - 34, "left"),
                ("다음", "next", 16, "left")]
    elif section == "승인":
        cols = [("유형", "category", 10, "left"),
                ("제목", "title", tw - 12, "left")]
    else:  # 기억
        cols = [("존", "zone", tw - 14, "left"), ("노트", "count", 6, "right")]

    header = "  " + "  ".join(
        ui.pad(lbl, w, align=al) for lbl, _k_, w, al in cols)
    out.append(f"{D}{ui.fit(header, tw)}{RST_}")

    # An empty pane and a broken backend used to render identically. The
    # 승인 pane claiming "nothing needs you" when it merely could not read is
    # the one version of that lie which costs something.
    err = (snap.get("errors") or {}).get(section)
    if err:
        out.append(f"{ui.RED}{ui.fit(f'  (불러오기 실패: {err})', tw)}{RST_}")

    if not rows:
        if not err:
            out.append(f"{D}  (없음){RST_}")
        return out

    cap = _row_capacity(height, len(rows), extra=1 if err else 0)
    visible = rows[top:top + cap]
    for i, row in enumerate(visible, start=top):
        cells = "  ".join(
            ui.pad(str(row.get(key, "")), w, align=al)
            for _lbl, key, w, al in cols)
        # ASCII marker (guaranteed width-1) so the cursor row is distinguishable
        # even with color off — inverse is added on top when color is on.
        marker = "> " if i == cursor else "  "
        line = ui.fit(marker + cells, tw)
        out.append(f"{INV}{line}{RST_}" if i == cursor else line)
    if len(rows) > cap:
        out.append(f"{D}  {cursor + 1}/{len(rows)}  ↓ 더 있음{RST_}")
    return out


def _rail_lines(snap: dict[str, Any], active: str, height: int) -> list[str]:
    C, D, B, RST_ = ui.CYAN, ui.DIM, ui.BOLD, ui.RESET
    counts = _counts(snap)
    out = []
    for i, s in enumerate(SECTIONS, 1):
        mark = "▸" if s == active else " "
        style = f"{B}{C}" if s == active else D
        # A confident "0" next to a pane that failed to load is the lie
        # the rail is most able to tell, since it is what you glance at.
        badge = "!" if (snap.get("errors") or {}).get(s) else counts[s]
        out.append(ui.pad(f"{style}{mark}{i} {s} {badge}{RST_}", _RAIL_W))
    while len(out) < height:
        out.append(" " * _RAIL_W)
    return out


def _hint_line(section: str, width: int = 200, note: str = "") -> str:
    if note:
        return f"{ui.BOLD}  {ui.fit(note, width - 2)}{ui.RESET}"
    base = "1-4 페인 · j/k 이동 · g/G 처음끝 · r 새로 · q 종료"
    extra = {"세션": " · Enter 열기", "크론": "", "승인": " · a 승인 · d 거부",
             "기억": ""}[section]
    return f"{ui.DIM}  {ui.fit(base + extra, width - 2)}{ui.RESET}"


def render(snap: dict[str, Any], state: dict[str, Any],
           size: tuple[int, int]) -> list[str]:
    """Compose the full-screen frame as a list of lines. Pure."""
    cols, rows_h = size
    tw = max(20, cols - _RAIL_W - 3)
    active = state["section"]
    lines: list[str] = []
    lines += _header_lines(snap, cols)
    lines.append(ui.DIM + "─" * min(cols, 100) + ui.RESET)

    body_h = _body_h(rows_h)
    rail = _rail_lines(snap, active, body_h)
    table = _table_lines(snap, active, state["cursor"], state["top"], body_h, tw)
    for i in range(body_h):
        r = rail[i] if i < len(rail) else " " * _RAIL_W
        t = table[i] if i < len(table) else ""
        lines.append(f"{r}{ui.DIM}│{ui.RESET} {t}")

    lines.append("")
    lines.append(_hint_line(active, cols, state.get("note", "")))
    return lines[:rows_h]


# -- plain / json fallback (non-TTY) ---------------------------------------

def dump_plain(snap: dict[str, Any], as_json: bool = False) -> str:
    if as_json:
        import json
        safe = {k: v for k, v in snap.items() if k != "cfg"}
        return json.dumps(safe, ensure_ascii=False, indent=2, default=str)
    h = snap["header"]
    out = [f"birkin mission control — {h['model']}·{h['provider']}"]
    errors = snap.get("errors") or {}
    for s in SECTIONS:
        err = errors.get(s)
        out.append(f"\n[{s}] ({len(_rows(snap, s))})"
                   + (f"  불러오기 실패: {err}" if err else ""))
        for row in _rows(snap, s)[:20]:
            out.append("  " + " · ".join(f"{k}={v}" for k, v in row.items()
                                         if k != "path"))
    return "\n".join(out)


# -- key input -------------------------------------------------------------

class _Keys:
    """Blocking single-key reader with a timeout, cross-platform."""

    def __init__(self):
        self._posix = os.name != "nt"
        self._fd = None
        self._old = None
        if self._posix:
            import termios
            import tty
            self._fd = sys.stdin.fileno()
            self._old = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)

    def read(self, timeout: float) -> str | None:
        if self._posix:
            import select
            r, _, _ = select.select([self._fd], [], [], timeout)
            if not r:
                return None
            ch = os.read(self._fd, 1).decode("utf-8", "ignore")
            if ch == "\x1b":                       # arrow / esc
                r2, _, _ = select.select([self._fd], [], [], 0.02)
                if not r2:
                    return "esc"
                seq = os.read(self._fd, 2).decode("utf-8", "ignore")
                return {"[A": "up", "[B": "down", "[C": "right",
                        "[D": "left"}.get(seq, "esc")
            return ch
        # Windows
        import msvcrt
        deadline = None
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):          # extended (arrows)
                    code = msvcrt.getwch()
                    return {"H": "up", "P": "down", "K": "left",
                            "M": "right"}.get(code, "")
                return ch
            if deadline is None:
                deadline = time.monotonic() + timeout
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.02)

    def restore(self):
        if self._posix and self._old is not None:
            import termios
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            except Exception:
                pass


# -- main loop -------------------------------------------------------------

def run(session: Any, *, plain: bool = False, as_json: bool = False) -> None:
    """Enter the dashboard. Falls back to a plain dump when not a TTY."""
    if plain or as_json or not sys.stdout.isatty():
        print(dump_plain(snapshot(session), as_json=as_json))
        return

    w = sys.stdout.write
    keys = _Keys()

    def restore():
        w(SHOW + RST + ALT_OFF)
        sys.stdout.flush()
        keys.restore()

    w(ALT_ON + HIDE)
    sys.stdout.flush()
    atexit.register(restore)
    state = {"section": "세션", "cursor": 0, "top": 0}
    try:
        _loop(session, w, keys, state)
    except KeyboardInterrupt:
        pass
    finally:
        restore()
        try:
            atexit.unregister(restore)
        except Exception:
            pass


def _size() -> tuple[int, int]:
    try:
        s = os.get_terminal_size()
        return s.columns, s.lines
    except OSError:
        return 80, 24


def _clamp_cursor(snap, state, body_h):
    rows = _rows(snap, state["section"])
    state["cursor"] = max(0, min(state["cursor"], max(0, len(rows) - 1)))
    if state["cursor"] < state["top"]:
        state["top"] = state["cursor"]
    elif state["cursor"] >= state["top"] + body_h:
        state["top"] = state["cursor"] - body_h + 1


def _loop(session, w, keys, state):
    snap = snapshot(session)
    last = time.monotonic()
    while True:
        size = _size()
        body_h = _body_h(size[1])
        # Clamp against what is actually PAINTED, not the slot height.
        _clamp_cursor(snap, state, _row_capacity(
            body_h, len(_rows(snap, state["section"]))))
        frame = render(snap, state, size)
        w(SYNC_ON + HOME)
        for line in frame:
            w(line + EL + "\r\n")
        w(EL + SYNC_OFF)
        sys.stdout.flush()

        key = keys.read(_REFRESH_S)
        now = time.monotonic()
        if key is None:
            if now - last >= _REFRESH_S:          # ambient refresh
                snap = snapshot(session)
                last = now
            continue

        rows = _rows(snap, state["section"])
        state["note"] = ""                  # any keypress clears the last one
        if key in ("q", "esc"):
            return
        elif key in ("1", "2", "3", "4"):
            state.update(section=SECTIONS[int(key) - 1], cursor=0, top=0)
        elif key == "\t":
            i = (SECTIONS.index(state["section"]) + 1) % len(SECTIONS)
            state.update(section=SECTIONS[i], cursor=0, top=0)
        elif key in ("j", "down"):
            state["cursor"] += 1
        elif key in ("k", "up"):
            state["cursor"] -= 1
        elif key == "g":
            state["cursor"] = 0
        elif key == "G":
            state["cursor"] = len(rows) - 1
        elif key == "r":
            snap = snapshot(session)
            last = now
        elif key == "\r" and state["section"] == "세션" and rows:
            _open_session(session, rows[state["cursor"]])
            return                                 # leave dash into the loaded convo
        elif state["section"] == "승인" and rows and key in ("a", "d"):
            out = _resolve_approval(rows[state["cursor"]],
                                    approve=(key == "a"))
            # Approving a queued shell command used to print nothing at all:
            # success, a non-zero exit and a raised exception were the same
            # blank screen. The row vanishing is not an outcome report.
            state["note"] = (f"\u2713 {str(out.get('result') or '완료')[:120]}"
                             if out.get("ok")
                             else f"\u26a0 {out.get('error') or '실패'}")
            snap = snapshot(session)


def _open_session(session, row):
    """Load the selected saved conversation (best-effort)."""
    try:
        from . import slashcommands
        slashcommands.dispatch(session, f"/load {row['title']}")
    except Exception:
        pass


def _resolve_approval(row, *, approve: bool) -> dict[str, Any]:
    try:
        from . import approvals
        fn = approvals.approve if approve else approvals.reject
        return fn(row["id"]) or {"ok": False, "error": "결과 없음"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}
