"""Component kit: pure renderers shared by every terminal surface.

Each function returns plain strings (or lists of lines) already fitted to the
requested cell width via :func:`birkin.ui.fit`, so callers only stack lines.
``color=False`` must produce zero escape codes; ``ascii_only=True`` swaps
state glyphs for their ASCII twins. No function here executes anything —
rendering is the entire job (UI proposes, Python disposes).
"""
from __future__ import annotations

from typing import Any

from . import ui_tokens, uistate
from .ui import cell_width, fit

_RESET = "\x1b[0m"


def _paint(text: str, role: str, color: bool) -> str:
    if not color:
        return text
    esc = ui_tokens.sgr(role)
    return f"{esc}{text}{_RESET}" if esc else text


def badge(state: str, *, color: bool, ascii_only: bool = False) -> str:
    """`◆ 응답대기` — glyph + label; color is the fourth channel, never the only one."""
    mark = uistate.glyph(state, ascii_only=ascii_only)
    text = uistate.label(state)
    if ascii_only:
        text = state.replace("_", " ")
    return _paint(f"{mark} {text}", uistate.color_role(state), color)


def session_row(item: dict[str, Any], width: int, *, color: bool,
                ascii_only: bool = False) -> str:
    """One Ledger line: state glyph anchors the eye, title carries identity."""
    view_state = str(item.get("state", "unknown"))
    mark = uistate.glyph(view_state, ascii_only=ascii_only)
    age = str(item.get("age", ""))
    tail = f" {age}" if age else ""
    body_w = max(1, width - cell_width(mark) - 1 - cell_width(tail))
    body = fit(str(item.get("title", "")), body_w)
    line = f"{mark} {body}{tail}"
    plain = fit(line, width)
    if not color:
        return plain
    return _paint(mark, uistate.color_role(view_state), color) + plain[len(mark):]


def approval_card(record: dict[str, Any], width: int, *, color: bool,
                  ascii_only: bool = False) -> list[str]:
    """Guardrail view: who asks, what runs, on what, until when, else what."""
    view = uistate.from_approval(record)
    payload = record.get("payload") or {}
    action = str(payload.get("command") or payload.get("action")
                 or record.get("description", ""))
    lines = [
        f"{badge(view.state, color=color, ascii_only=ascii_only)}"
        f"  {record.get('category', '?')}",
        str(record.get("title", "")),
        f"요청 주체: {record.get('origin', '?')}",
        f"동작: {action}",
    ]
    desc = str(record.get("description", ""))
    if desc and desc != action:
        lines.append(f"설명: {desc}")
    expires = record.get("expires_at")
    if expires:
        lines.append(f"만료: {expires}")
    if view.state == "waiting_human":
        lines.append("a 승인 · r 거부 — 승인 후 실행 주체: Python daemon")
        lines.append("거부 시: 동작은 실행되지 않고 기록만 남음")
    return [fit(line, width) for line in lines]


def tool_summary(tool: dict[str, Any], width: int, *, color: bool,
                 ascii_only: bool = False) -> str:
    """Collapsed one-liner that stays diagnosable: outcome + error head."""
    ok = tool.get("ok")
    # ok=None means the result has not arrived: render as running, never
    # as failed — streaming must not flicker through error states.
    state = "running" if ok is None else ("completed" if ok else "failed")
    mark = uistate.glyph(state, ascii_only=ascii_only)
    parts = [str(tool.get("name", "?"))]
    target = str(tool.get("target", ""))
    if target:
        parts.append(fit(target, 32))
    if not ok and tool.get("error"):
        parts.append(fit(str(tool["error"]), 40))
    duration = tool.get("duration_s")
    if duration is not None:
        parts.append(f"{float(duration):.1f}s")
    approval = str(tool.get("approval", ""))
    if approval:
        parts.append(approval)
    line = fit(f"{mark} " + " · ".join(parts), width)
    if not color:
        return line
    return _paint(mark, uistate.color_role(state), color) + line[len(mark):]


def tool_detail(tool: dict[str, Any], width: int, *, max_lines: int = 12,
                color: bool, ascii_only: bool = False) -> list[str]:
    """Expanded view, height-clamped: never let one tool own the screen."""
    lines = [tool_summary(tool, width, color=color, ascii_only=ascii_only)]
    output = str(tool.get("output", ""))
    if output:
        body = output.splitlines()
        shown = body[:max_lines]
        lines.extend(fit(ln, width) for ln in shown)
        rest = len(body) - len(shown)
        if rest > 0:
            lines.append(fit(f"… {rest}줄 더 보기 (Space)", width))
    return lines


def composer(mode: str, state: str, width: int, *, color: bool,
             ascii_only: bool = False) -> list[str]:
    """Borderless input surface: mode + blocking state above, hints below."""
    status = f"{badge(state, color=color, ascii_only=ascii_only)}  {mode}"
    prompt = "> " if ascii_only else "❯ "
    hints = "Enter 전송 · Esc 취소 · / 명령 · ? 도움"
    if state == "waiting_human":
        hints = "a 승인 · r 거부 · " + hints
    return [fit(status, width), fit(prompt, width),
            fit(_paint(hints, "muted", color), width)]


def status_pulse(info: dict[str, Any], width: int, *, color: bool) -> str:
    """One-line pulse: connection first — a dead daemon changes everything."""
    segments = []
    if info.get("daemon_up"):
        segments.append("데몬 연결")
    else:
        segments.append("데몬 오프라인")
    if info.get("model"):
        segments.append(str(info["model"]))
    pending = int(info.get("pending") or 0)
    if pending:
        segments.append(f"{uistate.glyph('waiting_human')} 대기 {pending}")
    if info.get("goal"):
        segments.append(f"목표 {info['goal']}")
    if info.get("cost"):
        segments.append(str(info["cost"]))
    return fit(" · ".join(segments), width)


def worker_tree(runs: list[dict[str, Any]], width: int, *, color: bool,
                ascii_only: bool = False) -> list[str]:
    """Indented run tree; stale runs render as unknown, never as alive."""
    lines = []
    for run in runs:
        view = uistate.from_agent_run(str(run.get("status", "")))
        indent = "  " * int(run.get("depth") or 0)
        mark = uistate.glyph(view.state, ascii_only=ascii_only)
        task_w = max(1, width - cell_width(indent) - cell_width(mark) - 1)
        line = f"{indent}{mark} {fit(str(run.get('task', '')), task_w)}"
        plain = fit(line, width)
        if color:
            plain = plain.replace(
                mark, _paint(mark, uistate.color_role(view.state), color), 1)
        lines.append(plain)
    return lines


def empty_state(message: str, width: int, *, color: bool) -> list[str]:
    return [fit(_paint(message, "muted", color), width)]


def error_state(message: str, width: int, *, color: bool) -> list[str]:
    mark = uistate.glyph("failed")
    return [fit(_paint(f"{mark} {message}", "failure", color), width)]


def disconnected_state(recovery_cmd: str, width: int, *,
                       color: bool) -> list[str]:
    """Reattach principle: always print the way back on screen."""
    return [
        fit(_paint("데몬과 연결이 끊어졌습니다", "warning", color), width),
        fit(f"복구: {recovery_cmd}", width),
        fit(_paint("연결되면 승인·작업 상태를 다시 불러옵니다", "muted", color),
            width),
    ]
