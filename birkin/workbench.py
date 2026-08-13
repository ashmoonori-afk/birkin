"""Workbench — attention-first full-screen surface (Ledger/Bench/Pulse).

Successor surface to ``/dash`` implementing docs/ui/DESIGN.md: the first
screen is an attention queue (Ledger) sorted by ``uistate.attention_rank``,
the Bench shows the selected work in depth, and a one-line Pulse keeps
connection/model/pending counts in view. Layout follows terminal width:
wide/medium keep Ledger and Bench side by side, narrow (<80 cols) switches
to a single surface with a summary switcher — never a crushed multi-column.

Same purity discipline as dash.py: ``snapshot`` gathers, ``render`` is a
pure function over (snap, state, size), only ``run`` touches the terminal.
The UI holds no execution authority: resolving an approval is a *request*
to the approvals module (Python authority); screen state changes only after
that call returns.
"""
from __future__ import annotations

import atexit
import os
import sys
import time
from typing import Any

from . import ui, uikit, uistate

ALT_ON, ALT_OFF = "\033[?1049h", "\033[?1049l"
HIDE, SHOW = "\033[?25l", "\033[?25h"
SYNC_ON, SYNC_OFF = "\033[?2026h", "\033[?2026l"
HOME, EL, ERASE_DOWN = "\033[H", "\033[0K", "\033[0J"

_NARROW = 80          # below this: single surface + switcher
_RAIL_W = 34
_CHROME_H = 4         # title+pulse, separator, hint
_REFRESH_S = 2.0


def initial_state() -> dict[str, Any]:
    return {"screen": "overview", "cursor": 0, "top": 0, "note": ""}


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes", "on")


# -- snapshot (impure gather, resilient per domain) -------------------------

def snapshot(session: Any) -> dict[str, Any]:
    """Collect everything the surface renders; failures degrade per pane."""
    from . import dash
    base = dash.snapshot(session)
    snap: dict[str, Any] = {
        "header": base.get("header", {}),
        "sessions": base.get("sessions", []),
        "agents": base.get("agents", []),
        "cron": base.get("cron", []),
        "approvals": [],
        "goal": {},
        "errors": dict(base.get("errors") or {}),
    }
    try:
        from . import approvals, store
        snap["approvals"] = list(approvals.reviewable_pending())
        for status in ("error", "expired"):
            snap["approvals"].extend(store.list_resolved(status)[-3:])
    except Exception as exc:
        snap["errors"]["승인"] = str(exc) or type(exc).__name__
    try:
        from . import goals
        active = goals.get_active()
        if active:
            snap["goal"] = {"status": getattr(active, "status", ""),
                            "objective": getattr(active, "objective", "")}
    except Exception:
        pass
    return snap


# -- ledger (pure) ----------------------------------------------------------

def build_ledger(snap: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten every domain into one attention-sorted queue."""
    items: list[dict[str, Any]] = []
    for rec in snap.get("approvals", []):
        items.append({"kind": "approval", "id": rec.get("id", ""),
                      "title": rec.get("title", "") or rec.get("category", "?"),
                      "age": "", "view": uistate.from_approval(rec),
                      "record": rec})
    for run in snap.get("agents", []):
        items.append({"kind": "agent", "id": run.get("id", ""),
                      "title": run.get("task", "") or run.get("id", ""),
                      "age": run.get("age", ""),
                      "view": uistate.from_agent_run(str(run.get("status", ""))),
                      "record": run})
    goal = snap.get("goal") or {}
    if goal.get("status"):
        items.append({"kind": "goal", "id": "goal",
                      "title": goal.get("objective", "목표"), "age": "",
                      "view": uistate.from_goal(str(goal["status"])),
                      "record": goal})
    for sess in snap.get("sessions", []):
        items.append({"kind": "session", "id": sess.get("path", ""),
                      "title": sess.get("title", ""),
                      "age": sess.get("age", ""),
                      "view": uistate.StateView("idle", "saved", "session"),
                      "record": sess})
    for job in snap.get("cron", []):
        state = "idle" if job.get("enabled", True) else "paused"
        items.append({"kind": "cron", "id": str(job.get("id", "")),
                      "title": job.get("name", "?"),
                      "age": job.get("next", ""),
                      "view": uistate.StateView(state, "scheduled", "cron"),
                      "record": job})
    items.sort(key=lambda it: uistate.attention_rank(it["view"].state))
    return items


def _waiting_count(items: list[dict[str, Any]]) -> int:
    return sum(1 for it in items if it["view"].state == "waiting_human")


# -- rendering (pure) -------------------------------------------------------

def _pulse_info(snap: dict[str, Any], items: list[dict[str, Any]]) -> dict:
    header = snap.get("header", {})
    return {"model": header.get("model", ""),
            "daemon_up": bool(header.get("daemon_up")),
            "pending": _waiting_count(items),
            "goal": (snap.get("goal") or {}).get("status", ""),
            "cost": ""}


def _bench_preview(item: dict[str, Any], width: int, height: int, *,
                   color: bool, ascii_only: bool) -> list[str]:
    kind = item.get("kind")
    if kind == "approval":
        return uikit.approval_card(item["record"], width, color=color,
                                   ascii_only=ascii_only)[:height]
    if kind == "agent":
        return uikit.worker_tree([item["record"]], width, color=color,
                                 ascii_only=ascii_only)[:height]
    rec = item.get("record") or {}
    lines = [ui.fit(str(item.get("title", "")), width)]
    for key in ("schedule", "next", "age", "objective", "path"):
        if rec.get(key):
            lines.append(ui.fit(f"{key}: {rec[key]}", width))
    return lines[:height]


def _approval_screen(snap: dict[str, Any], state: dict[str, Any],
                     width: int, height: int, *, color: bool,
                     ascii_only: bool) -> list[str]:
    items = [it for it in build_ledger(snap) if it["kind"] == "approval"]
    idx = min(state.get("cursor", 0), max(0, len(items) - 1))
    if not items:
        return uikit.empty_state("승인 대기 항목 없음", width, color=color)
    lines = uikit.approval_card(items[idx]["record"], width, color=color,
                                ascii_only=ascii_only)
    payload = items[idx]["record"].get("payload") or {}
    if payload:
        lines.append(ui.fit(f"예상 영향: {len(payload)}개 항목 변경 요청",
                            width))
    if state.get("note"):
        lines.append(ui.fit(str(state["note"]), width))
    lines.append(ui.fit("Esc 뒤로 · a 승인 요청 · r 거부 요청", width))
    return lines[:height]


_KEYMAP: tuple[tuple[str, str, str], ...] = (
    ("탐색", "j/k 또는 ↑/↓", "이동"), ("탐색", "Enter", "열기"),
    ("탐색", "g/G", "처음/끝"),
    ("상세", "Space", "tool detail 접기/펼치기"),
    ("상세", "n/p", "다음/이전 tool"),
    ("상세", "[/]", "세션 위/아래 스크롤"),
    ("승인", "a", "승인 요청"), ("승인", "r", "거부 요청"),
    ("화면", "f", "authority snapshot 새로고침"),
    ("화면", "?", "도움"), ("화면", "/", "도움 검색"),
    ("화면", "Esc", "뒤로"), ("화면", "q", "종료"),
)


def update_help_search(state: dict[str, Any], key: str) -> bool:
    """Apply one help-search key, returning whether it was consumed."""
    if key == "/":
        state.update(screen="help", query="", searching=True)
        return True
    if state.get("screen") != "help" or not state.get("searching"):
        return False
    if key == "esc":
        state["screen"] = "overview"
        state.pop("query", None)
        state.pop("searching", None)
    elif key in ("\x7f", "\x08"):
        state["query"] = str(state.get("query", ""))[:-1]
    elif len(key) == 1 and key.isprintable():
        state["query"] = str(state.get("query", "")) + key
    return True


def _help_screen(width: int, height: int, query: str,
                 searching: bool = False) -> list[str]:
    """Render the keymap grouped by task, never a flat dump."""
    q = (query or "").strip()
    title = "도움 — 키맵"
    if searching:
        title += f" (검색: {q}_ · Esc 닫기)"
    lines = [ui.fit(title, width)]
    for group in dict.fromkeys(g for g, _, _ in _KEYMAP):
        entries = [(key, label) for g, key, label in _KEYMAP
                   if g == group and (not q or q in g or q in key
                                      or q in label)]
        if not entries:
            continue
        lines.append(ui.fit(f"[{group}]", width))
        for key, label in entries:
            lines.append(ui.fit(f"  {key}  {label}", width))
    return lines[:height]


def render(snap: dict[str, Any], state: dict[str, Any],
           size: tuple[int, int], *, color: bool | None = None,
           ascii_only: bool | None = None) -> list[str]:
    """Compose the frame as a list of lines. Pure; never touches a TTY."""
    cols, rows = size
    color = ui.should_color() if color is None else color
    ascii_only = (_env_enabled("BIRKIN_ASCII") if ascii_only is None
                  else ascii_only)
    items = build_ledger(snap)
    body_h = max(3, rows - _CHROME_H)
    pulse = uikit.status_pulse(_pulse_info(snap, items), cols, color=color,
                               ascii_only=ascii_only)
    sep = ui.fit("─" * cols if not ascii_only else "-" * cols, cols)

    lines = [ui.fit("birkin workbench", cols), pulse, sep]

    if state.get("screen") == "approval":
        lines += _approval_screen(snap, state, cols, body_h, color=color,
                                  ascii_only=ascii_only)
    elif state.get("screen") == "session":
        lines += render_session(
            state.get("messages") or [], state.get("expanded") or set(),
            cols, body_h, color=color, ascii_only=ascii_only,
            tool_cursor=state.get("tool_cursor", 0),
            scroll=state.get("session_scroll", 0),
        )
    elif state.get("screen") == "help":
        lines += _help_screen(cols, body_h, str(state.get("query", "")),
                              bool(state.get("searching")))
    elif cols < _NARROW:
        waiting = _waiting_count(items)
        lines.append(ui.fit(f"주의 필요 — 대기 {waiting}", cols))
        top = state.get("top", 0)
        for i, item in enumerate(items[top:top + body_h - 1], start=top):
            row = uikit.session_row(
                {"title": item["title"], "state": item["view"].state,
                 "age": item["age"]}, cols - 2, color=color,
                ascii_only=ascii_only)
            marker = ">" if i == state.get("cursor", 0) else " "
            lines.append(ui.fit(f"{marker} {row}", cols))
    else:
        # medium (<100 cols): glyph-only rail — density is modal, titles are
        # never crushed to fit (Herdr principle, Birkin geometry).
        compact = cols < 100
        rail_w = 4 if compact else min(_RAIL_W, max(20, cols // 3))
        bench_w = cols - rail_w - 3
        cursor = min(state.get("cursor", 0), max(0, len(items) - 1))
        rail: list[str] = []
        top = state.get("top", 0)
        for i, item in enumerate(items[top:top + body_h], start=top):
            marker = ">" if i == cursor else " "
            if compact:
                mark = uistate.glyph(item["view"].state,
                                     ascii_only=ascii_only)
                row = mark
            else:
                row = uikit.session_row(
                    {"title": item["title"], "state": item["view"].state,
                     "age": item["age"]}, rail_w - 2, color=color,
                    ascii_only=ascii_only)
            rail.append(ui.pad(ui.fit(f"{marker} {row}", rail_w), rail_w))
        bench = (_bench_preview(items[cursor], bench_w, body_h, color=color,
                                ascii_only=ascii_only)
                 if items else
                 uikit.empty_state("표시할 작업 없음", bench_w, color=color))
        bar = "|" if ascii_only else "│"
        for i in range(min(body_h, max(len(rail), len(bench)))):
            left = rail[i] if i < len(rail) else " " * rail_w
            right = bench[i] if i < len(bench) else ""
            lines.append(ui.fit(f"{left} {bar} {right}", cols))

    if not snap.get("header", {}).get("daemon_up") and state.get(
            "screen") != "approval":
        lines += uikit.disconnected_state("birkin daemon start", cols,
                                          color=color)[:2]
    hint = "j/k 이동 · Enter 열기 · a 승인 · r 거부 · f 새로고침 · q 종료"
    if state.get("screen") == "session":
        hint = "n/p tool · Space 상세 · [/] 스크롤 · Esc 뒤로 · q 종료"
    if state.get("note") and state.get("screen") != "approval":
        hint = str(state["note"])
    lines.append(ui.fit(hint, cols))
    return lines[:rows]


# -- session work surface (pure) --------------------------------------------

def _tool_target(tool_input: dict[str, Any]) -> str:
    for key in ("command", "path", "url", "query", "name"):
        if tool_input.get(key):
            return str(tool_input[key])
    return next((str(v) for v in tool_input.values()
                 if isinstance(v, str) and v), "")


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content
                         if isinstance(b, dict))
    return str(content or "")


def session_view(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Split a saved transcript into conversation turns and tool executions."""
    turns: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    pending: dict[str, dict[str, Any]] = {}
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if not role or not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text" and block.get("text"):
                turns.append({"role": role, "text": str(block["text"])})
            elif kind == "tool_use":
                entry = {"name": block.get("name", "?"),
                         "target": _tool_target(block.get("input") or {}),
                         "ok": None, "output": "", "error": ""}
                pending[str(block.get("id", ""))] = entry
                tools.append(entry)
            elif kind == "tool_result":
                entry = pending.pop(str(block.get("tool_use_id", "")), None)
                if entry is None:
                    continue
                text = _result_text(block.get("content"))
                if block.get("is_error"):
                    entry["ok"] = False
                    entry["error"] = text
                else:
                    entry["ok"] = True
                    entry["output"] = text
    return {"turns": turns, "tools": tools}


def render_session(messages: list[dict[str, Any]], expanded: set[int],
                   cols: int, rows: int, *, color: bool,
                   ascii_only: bool = False, tool_cursor: int = 0,
                   scroll: int = 0) -> list[str]:
    """Conversation and tool executions in a clamped scrollback viewport."""
    view = session_view(messages)
    lines: list[str] = []
    for turn in view["turns"]:
        marker = ">" if turn["role"] == "user" else " "
        first = turn["text"].splitlines()[0] if turn["text"] else ""
        lines.append(ui.fit(f"{marker} {first}", cols))
    if view["tools"]:
        lines.append(ui.fit("─" * cols if not ascii_only else "-" * cols,
                            cols))
    for idx, tool in enumerate(view["tools"]):
        if idx in expanded:
            tool_lines = uikit.tool_detail(tool, max(1, cols - 2),
                                            max_lines=8, color=color,
                                            ascii_only=ascii_only)
        else:
            tool_lines = [uikit.tool_summary(
                tool, max(1, cols - 2), color=color,
                ascii_only=ascii_only,
            )]
        cursor = "> " if idx == tool_cursor else "  "
        lines.append(ui.fit(cursor + tool_lines[0], cols))
        lines.extend(ui.fit("  " + line, cols) for line in tool_lines[1:])
    offset = max(0, min(int(scroll), max(0, len(lines) - rows)))
    end = len(lines) - offset
    start = max(0, end - rows)
    return lines[start:end]


def _load_transcript(path: str) -> list[dict[str, Any]]:
    try:
        import json
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:
        return []


# -- authority boundary -----------------------------------------------------

def resolve_approval(aid: str, *, approve: bool) -> dict[str, Any]:
    """Request a resolution from the Python authority; report, never assume."""
    try:
        from . import approvals
        fn = approvals.approve if approve else approvals.reject
        return fn(aid) or {"ok": False, "error": "결과 없음"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


# -- main loop --------------------------------------------------------------

def _size() -> tuple[int, int]:
    try:
        import os
        s = os.get_terminal_size()
        return s.columns, s.lines
    except OSError:
        return 80, 24


def run(session: Any, *, plain: bool = False, as_json: bool = False) -> None:
    """Enter the workbench; non-TTY degrades to a plain/JSON dump."""
    snap = snapshot(session)
    if plain or as_json or not sys.stdout.isatty():
        if as_json:
            import json
            print(json.dumps({k: v for k, v in snap.items() if k != "cfg"},
                             ensure_ascii=False, indent=2, default=str))
        else:
            for line in render(snap, initial_state(), (80, 200), color=False):
                print(line)
        return

    from .dash import _Keys
    w = sys.stdout.write
    keys = _Keys()

    def restore() -> None:
        w(SHOW + "\033[0m" + ALT_OFF)
        sys.stdout.flush()
        keys.restore()

    w(ALT_ON + HIDE)
    sys.stdout.flush()
    atexit.register(restore)
    state = initial_state()
    try:
        _loop(session, snap, w, keys, state)
    except KeyboardInterrupt:
        pass
    finally:
        restore()
        try:
            atexit.unregister(restore)
        except Exception:
            pass


def _loop(session: Any, snap: dict[str, Any], w, keys,
          state: dict[str, Any]) -> None:
    last = time.monotonic()
    while True:
        size = _size()
        items = build_ledger(snap)
        body_h = max(3, size[1] - _CHROME_H)
        state["cursor"] = max(0, min(state["cursor"], len(items) - 1))
        if state["cursor"] < state["top"]:
            state["top"] = state["cursor"]
        elif state["cursor"] >= state["top"] + body_h - 1:
            state["top"] = state["cursor"] - body_h + 2
        w(SYNC_ON + HOME)
        for line in render(snap, state, size):
            w(line + EL + "\r\n")
        w(EL + ERASE_DOWN + SYNC_OFF)
        sys.stdout.flush()

        key = keys.read(_REFRESH_S)
        now = time.monotonic()
        if key is None:
            if now - last >= _REFRESH_S:
                snap = snapshot(session)
                last = now
            continue
        state["note"] = ""
        if key == "paste":
            continue
        if update_help_search(state, key):
            continue
        if key not in ("a", "r"):
            state.pop("confirmation", None)
        if key == "q":
            return
        if key == "esc":
            if state["screen"] != "overview":
                state["screen"] = "overview"
                continue
            return
        if key in ("j", "down"):
            state["cursor"] += 1
        elif key in ("k", "up"):
            state["cursor"] -= 1
        elif key == "g":
            state["cursor"] = 0
        elif key == "G":
            state["cursor"] = max(0, len(items) - 1)
        elif key == "?":
            state["screen"] = "help"
        elif key == "f":
            snap = snapshot(session)
            last = now
        elif key == "\r" and items:
            item = items[state["cursor"]]
            if item["kind"] == "approval":
                state["screen"] = "approval"
            elif item["kind"] == "session":
                state["messages"] = _load_transcript(str(item["id"]))
                state["expanded"] = set()
                state["tool_cursor"] = 0
                state["session_scroll"] = 0
                state["screen"] = "session"
        elif key == " " and state["screen"] == "session":
            expanded = state.setdefault("expanded", set())
            idx = state.get("tool_cursor", 0)
            expanded.symmetric_difference_update({idx})
        elif key in ("[", "]") and state["screen"] == "session":
            step = max(1, body_h // 2)
            current = int(state.get("session_scroll", 0))
            state["session_scroll"] = max(
                0, current + (step if key == "[" else -step))
        elif key in ("n", "p") and state["screen"] == "session":
            tools = session_view(state.get("messages") or [])["tools"]
            step = 1 if key == "n" else -1
            state["tool_cursor"] = max(
                0, min(state.get("tool_cursor", 0) + step,
                       max(0, len(tools) - 1)))
        elif key in ("a", "r") and items:
            item = items[state["cursor"]]
            if item["kind"] != "approval":
                continue
            confirmation = (item["id"], key)
            if state.get("confirmation") != confirmation:
                state["confirmation"] = confirmation
                label = "승인" if key == "a" else "거부"
                state["note"] = f"{label} 요청 확인: 같은 키를 다시 누르세요"
                continue
            state.pop("confirmation", None)
            state["note"] = "요청 전송 중"
            out = resolve_approval(item["id"], approve=(key == "a"))
            state["note"] = (f"✓ {str(out.get('result') or '처리됨')[:100]}"
                             if out.get("ok")
                             else f"⚠ {out.get('error') or '실패'}")
            snap = snapshot(session)
            last = now
