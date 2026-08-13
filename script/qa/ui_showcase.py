"""Component showcase: render every uikit component in one palette.

Usage:
    python script/qa/ui_showcase.py [--palette atelier|observatory|jade]
                                    [--width N] [--no-color] [--ascii]

Renders the full component inventory (docs/ui/DESIGN.md §6) with fixture data
including CJK strings, so the three visual directions can be compared on real
components before a screen is built. Read-only; executes nothing.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from birkin import ui_tokens, uikit, uistate  # noqa: E402


def render(palette: str, width: int, color: bool, ascii_only: bool) -> str:
    ui_tokens.DEFAULT_PALETTE = palette
    out = io.StringIO()
    w = out.write

    def title(text: str) -> None:
        w("\n" + uikit._paint(f"── {text} ", "accent", color)
          + uikit._paint("─" * max(0, width - len(text) - 4), "muted", color)
          + "\n")

    w(uikit._paint(f"Birkin UI showcase · {palette} · {width} cols\n",
                   "text_primary", color))

    title("state badges")
    for state in uistate.UI_STATES:
        w("  " + uikit.badge(state, color=color, ascii_only=ascii_only) + "\n")

    title("session rows (Ledger)")
    rows = [
        {"title": "국내주식 리서치 세션", "state": "running", "age": "3m"},
        {"title": "결제 웹훅 계약 감사 — 아주 길어서 잘려야 하는 제목입니다",
         "state": "waiting_human", "age": "12m"},
        {"title": "nightly curation", "state": "completed", "age": "2h"},
        {"title": "morpheus digest", "state": "failed", "age": "5h"},
    ]
    for row in rows:
        w("  " + uikit.session_row(row, width - 2, color=color,
                                   ascii_only=ascii_only) + "\n")

    title("approval card")
    card = {
        "id": "abc123def456", "title": "위험한 셸 명령 실행",
        "description": "빌드 산출물 디렉터리를 삭제합니다",
        "category": "shell", "origin": "morpheus", "status": "pending",
        "payload": {"command": "rm -rf build/"},
        "expires_at": "2026-08-13T09:00:00+00:00",
    }
    for line in uikit.approval_card(card, width - 2, color=color,
                                    ascii_only=ascii_only):
        w("  " + line + "\n")

    title("tool summary → detail (progressive disclosure)")
    tool = {"name": "run_shell", "target": "pytest tests/ -q", "ok": True,
            "duration_s": 12.4, "approval": "auto",
            "output": "\n".join(f"tests/test_x.py::case_{i} PASSED"
                                for i in range(30))}
    w("  " + uikit.tool_summary(tool, width - 2, color=color,
                                ascii_only=ascii_only) + "\n")
    failed = {"name": "web_fetch", "target": "https://example.com/api",
              "ok": False, "duration_s": 3.1,
              "error": "HTTP 503 service unavailable"}
    w("  " + uikit.tool_summary(failed, width - 2, color=color,
                                ascii_only=ascii_only) + "\n")
    for line in uikit.tool_detail(tool, width - 2, max_lines=6, color=color,
                                  ascii_only=ascii_only):
        w("  " + line + "\n")

    title("worker tree")
    runs = [
        {"id": "aaaa", "task": "관제 리포트 생성", "status": "running",
         "depth": 0},
        {"id": "bbbb", "task": "증거 수집 서브에이전트", "status": "done",
         "depth": 1},
        {"id": "cccc", "task": "하트비트 소실 워커", "status": "stale",
         "depth": 1},
    ]
    for line in uikit.worker_tree(runs, width - 2, color=color,
                                  ascii_only=ascii_only):
        w("  " + line + "\n")

    title("composer + status pulse")
    for line in uikit.composer("chat", "waiting_human", width - 2,
                               color=color, ascii_only=ascii_only):
        w("  " + line + "\n")
    w("  " + uikit.status_pulse(
        {"model": "claude-sonnet-4-5", "daemon_up": True, "pending": 2,
         "cost": "$1.23", "goal": "active"}, width - 2, color=color) + "\n")

    title("empty / error / disconnected")
    w("  " + uikit.empty_state("승인 대기 항목 없음", width - 2,
                               color=color)[0] + "\n")
    w("  " + uikit.error_state("스냅샷 읽기 실패: boom", width - 2,
                               color=color)[0] + "\n")
    for line in uikit.disconnected_state("birkin daemon start", width - 2,
                                         color=color):
        w("  " + line + "\n")
    return out.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--palette", default="atelier",
                    choices=sorted(ui_tokens.PALETTES))
    ap.add_argument("--width", type=int, default=80)
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--ascii", action="store_true")
    args = ap.parse_args()
    text = render(args.palette, args.width, not args.no_color, args.ascii)
    data = text.encode("utf-8", errors="replace")
    sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
