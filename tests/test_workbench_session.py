"""Session Work Surface: conversation + progressive tool disclosure.

The Bench session screen is built from the saved transcript alone: text
blocks become conversation turns, tool_use/tool_result pairs become tool
executions rendered collapsed by default and expanded per item. Contracts:
correct pairing, collapsed = one line, expansion is bounded, and the whole
screen fits the contract sizes with CJK content.
"""
from __future__ import annotations

import re

from birkin import workbench
from birkin.ui import cell_width

ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

MESSAGES = [
    {"metadata": {"source": "repl", "model": "m"}},
    {"role": "user", "content": [
        {"type": "text", "text": "빌드 정리하고 테스트 돌려줘"}]},
    {"role": "assistant", "content": [
        {"type": "text", "text": "정리 후 테스트를 실행합니다."},
        {"type": "tool_use", "id": "t1", "name": "run_shell",
         "input": {"command": "pytest tests/ -q"}}]},
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "is_error": False,
         "content": "\n".join(f"case {i} passed" for i in range(40))}]},
    {"role": "assistant", "content": [
        {"type": "tool_use", "id": "t2", "name": "web_fetch",
         "input": {"url": "https://example.com"}}]},
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t2", "is_error": True,
         "content": "HTTP 503 service unavailable"}]},
    {"role": "assistant", "content": [
        {"type": "text", "text": "테스트는 통과, 웹 요청은 실패했습니다."}]},
]


def test_session_view_pairs_tools_with_results():
    view = workbench.session_view(MESSAGES)
    tools = view["tools"]
    assert len(tools) == 2
    assert tools[0]["name"] == "run_shell"
    assert tools[0]["target"] == "pytest tests/ -q"
    assert tools[0]["ok"] is True
    assert "case 0 passed" in tools[0]["output"]
    assert tools[1]["ok"] is False
    assert "503" in tools[1]["error"]


def test_session_view_extracts_conversation_turns():
    view = workbench.session_view(MESSAGES)
    texts = [t["text"] for t in view["turns"]]
    assert "빌드 정리하고 테스트 돌려줘" in texts
    assert "테스트는 통과, 웹 요청은 실패했습니다." in texts
    roles = {t["role"] for t in view["turns"]}
    assert roles == {"user", "assistant"}


def test_session_screen_collapses_tools_by_default():
    lines = workbench.render_session(MESSAGES, set(), 80, 24, color=False)
    text = "\n".join(lines)
    assert "run_shell" in text
    # collapsed: the 40-line output must not flood the screen
    assert "case 5 passed" not in text
    assert len(lines) <= 24


def test_session_screen_expands_one_tool_bounded():
    lines = workbench.render_session(MESSAGES, {0}, 80, 40, color=False)
    text = "\n".join(lines)
    assert "case 0 passed" in text
    assert any("더 보기" in ln for ln in lines)   # clamped, not dumped
    assert len(lines) <= 40


def test_session_screen_fits_contract_sizes():
    for cols, rows in ((60, 20), (80, 24), (120, 30), (160, 40)):
        lines = workbench.render_session(MESSAGES, {0, 1}, cols, rows,
                                         color=False)
        assert len(lines) <= rows
        for ln in lines:
            assert cell_width(ANSI.sub("", ln)) <= cols, (cols, repr(ln))


def test_session_screen_failure_tool_shows_error_in_summary():
    lines = workbench.render_session(MESSAGES, set(), 100, 30, color=False)
    text = "\n".join(lines)
    assert "503" in text
