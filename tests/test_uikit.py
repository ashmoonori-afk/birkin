"""Component kit: pure renderers shared by /dash, REPL surfaces and showcase.

Contracts under test: every component returns lines that fit the requested
width (CJK measured in cells, never characters), NO_COLOR output carries zero
escape codes yet still encodes state via glyph+label, long output is clamped
with an explicit overflow marker, and ASCII mode never emits non-ASCII state
glyphs.
"""
from __future__ import annotations

import re

from birkin import uikit, uistate
from birkin.ui import cell_width

ANSI = re.compile(r"\x1b\[[0-9;]*m")

KO_SESSION = {"title": "국내주식 리서치 세션", "state": "running",
              "age": "3m", "detail": "모델 응답 스트리밍"}
APPROVAL = {
    "id": "abc123def456", "title": "위험한 셸 명령 실행",
    "description": "rm -rf build/ 를 실행합니다", "category": "shell",
    "origin": "morpheus", "status": "pending",
    "payload": {"command": "rm -rf build/"},
    "expires_at": "2126-01-01T00:00:00+00:00",
}
TOOL = {"name": "run_shell", "target": "pytest tests/ -q", "ok": True,
        "duration_s": 12.4, "approval": "auto"}


def _flat(lines: list[str]) -> str:
    return "\n".join(lines)


def _assert_fits(lines: list[str], width: int) -> None:
    for line in lines:
        assert cell_width(ANSI.sub("", line)) <= width, repr(line)


# -- state badge ------------------------------------------------------------

def test_badge_carries_glyph_and_label_without_color():
    out = uikit.badge("waiting_human", color=False)
    assert ANSI.search(out) is None
    assert uistate.glyph("waiting_human") in out
    assert uistate.label("waiting_human") in out


def test_badge_ascii_mode_is_pure_ascii():
    for state in uistate.UI_STATES:
        out = uikit.badge(state, color=False, ascii_only=True)
        assert out.isascii(), (state, out)


def test_badge_colored_resolves_state_role_to_token_sgr():
    out = uikit.badge("failed", color=True)
    assert ANSI.search(out) is not None
    assert out.endswith("\x1b[0m")


# -- session row ------------------------------------------------------------

def test_session_row_fits_width_with_cjk():
    for width in (20, 40, 60, 120):
        line = uikit.session_row(KO_SESSION, width, color=False)
        assert cell_width(line) <= width, width


def test_session_row_keeps_state_when_narrow():
    line = uikit.session_row(KO_SESSION, 24, color=False)
    assert uistate.glyph("running") in line


# -- approval card ----------------------------------------------------------

def test_approval_card_shows_guardrail_fields():
    lines = uikit.approval_card(APPROVAL, 80, color=False)
    text = _flat(lines)
    assert "위험한 셸 명령 실행" in text
    assert "morpheus" in text          # 요청 주체
    assert "shell" in text             # 대상/카테고리
    assert "rm -rf build/" in text     # 실행하려는 동작
    _assert_fits(lines, 80)


def test_approval_card_never_renders_approve_as_done():
    lines = uikit.approval_card(APPROVAL, 80, color=False)
    text = _flat(lines)
    assert uistate.label("completed") not in text
    assert uistate.label("waiting_human") in text


def test_approval_card_fits_narrow_width():
    _assert_fits(uikit.approval_card(APPROVAL, 40, color=False), 40)


# -- tool summary + detail (progressive disclosure) -------------------------

def test_tool_summary_is_one_line_with_outcome_and_duration():
    line = uikit.tool_summary(TOOL, 80, color=False)
    assert "\n" not in line
    assert "run_shell" in line
    assert "12.4" in line or "12s" in line
    assert cell_width(line) <= 80


def test_tool_summary_failure_promotes_error():
    tool = dict(TOOL, ok=False, error="exit 1: FAILED tests/test_x.py")
    line = uikit.tool_summary(tool, 80, color=False)
    assert "exit 1" in line


def test_tool_detail_clamps_long_output_with_marker():
    tool = dict(TOOL, output="\n".join(f"line {i}" for i in range(200)))
    lines = uikit.tool_detail(tool, 80, max_lines=12, color=False)
    assert len(lines) <= 12 + 4  # header + clamp marker allowance
    assert any("더 보기" in ln or "more" in ln for ln in lines)
    _assert_fits(lines, 80)


def test_tool_detail_short_output_is_not_marked():
    tool = dict(TOOL, output="ok")
    lines = uikit.tool_detail(tool, 80, max_lines=12, color=False)
    assert not any("더 보기" in ln or "more" in ln for ln in lines)


# -- composer + status pulse ------------------------------------------------

def test_composer_shows_mode_and_blocked_state():
    lines = uikit.composer("chat", "waiting_human", 80, color=False)
    text = _flat(lines)
    assert uistate.label("waiting_human") in text
    _assert_fits(lines, 80)


def test_status_pulse_is_single_line_and_fits():
    info = {"model": "claude-sonnet-4-5", "daemon_up": True, "pending": 2,
            "cost": "$1.23", "goal": "active"}
    for width in (40, 80, 160):
        line = uikit.status_pulse(info, width, color=False)
        assert "\n" not in line
        assert cell_width(line) <= width


def test_status_pulse_disconnected_is_explicit():
    info = {"model": "m", "daemon_up": False, "pending": 0, "cost": "",
            "goal": ""}
    line = uikit.status_pulse(info, 80, color=False)
    assert "데몬" in line or "daemon" in line


# -- worker tree ------------------------------------------------------------

def test_worker_tree_indents_children_and_fits():
    runs = [
        {"id": "aaaa", "task": "상위 작업", "status": "running", "depth": 0},
        {"id": "bbbb", "task": "하위 작업 긴 이름" * 8, "status": "done",
         "depth": 1},
        {"id": "cccc", "task": "고아 작업", "status": "stale", "depth": 1},
    ]
    lines = uikit.worker_tree(runs, 60, color=False)
    assert len(lines) == 3
    _assert_fits(lines, 60)
    assert lines[1].startswith(" ")
    # stale maps to unknown, never invented liveness
    assert uistate.glyph("unknown") in lines[2]


# -- empty / error / disconnected states ------------------------------------

def test_terminal_states_render_and_fit():
    for lines in (
        uikit.empty_state("승인 대기 항목 없음", 40, color=False),
        uikit.error_state("스냅샷 읽기 실패: boom", 40, color=False),
        uikit.disconnected_state("birkin daemon start", 40, color=False),
    ):
        assert lines
        _assert_fits(lines, 40)


def test_disconnected_state_names_recovery_command():
    lines = uikit.disconnected_state("birkin daemon start", 60, color=False)
    assert any("birkin daemon start" in ln for ln in lines)


# -- color discipline -------------------------------------------------------

def test_no_color_means_no_escapes_anywhere():
    outputs = [
        uikit.badge("running", color=False),
        uikit.session_row(KO_SESSION, 60, color=False),
        _flat(uikit.approval_card(APPROVAL, 60, color=False)),
        uikit.tool_summary(TOOL, 60, color=False),
        _flat(uikit.composer("chat", "running", 60, color=False)),
        uikit.status_pulse({"model": "m", "daemon_up": True, "pending": 0,
                            "cost": "", "goal": ""}, 60, color=False),
    ]
    for out in outputs:
        assert ANSI.search(out) is None, out
