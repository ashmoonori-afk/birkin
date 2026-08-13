"""Responsive layout + keyboard discoverability + reconnect rendering.

Contracts: medium widths (80–99) compact the Ledger rail to a glyph column
instead of crushing titles; a searchable help screen lists the keymap by
task group; a downed daemon renders the recovery command and a healthy one
does not; every screen fits the four contract sizes.
"""
from __future__ import annotations

import re

from birkin import workbench
from birkin.ui import cell_width

ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

SNAP = {
    "header": {"model": "m", "provider": "p", "daemon_up": True,
               "daemon_known": True, "daemon_stale": False},
    "approvals": [
        {"id": "aaaa11112222", "category": "shell", "origin": "morpheus",
         "title": "빌드 정리 명령 실행", "status": "pending",
         "description": "rm -rf build/",
         "payload": {"command": "rm -rf build/"},
         "expires_at": "2126-01-01T00:00:00+00:00"},
    ],
    "sessions": [{"title": "국내주식 리서치 세션", "age": "3분전",
                  "path": "x.json"}],
    "agents": [], "cron": [], "goal": {}, "errors": {},
}


def _lines(state_extra: dict | None = None, size=(120, 30)) -> list[str]:
    state = workbench.initial_state()
    if state_extra:
        state.update(state_extra)
    return workbench.render(SNAP, state, size, color=False)


# -- medium: compact glyph rail, never crushed titles ------------------------

def test_medium_compacts_rail_to_glyph_column():
    lines = _lines(size=(90, 24))
    body = [ln for ln in lines if "│" in ln]
    assert body, "medium layout must keep rail and bench side by side"
    for ln in body:
        left = ln.split("│")[0]
        assert cell_width(left) <= 8, repr(ln)
    # the bench still carries the full title
    assert any("빌드 정리 명령 실행" in ln for ln in lines)


def test_wide_keeps_titled_rail():
    lines = _lines(size=(120, 30))
    rail_side = [ln.split("│")[0] for ln in lines if "│" in ln]
    assert any("빌드 정리" in part for part in rail_side)


# -- help overlay -------------------------------------------------------------

def test_help_screen_groups_keys_by_task():
    lines = _lines({"screen": "help"})
    text = "\n".join(lines)
    for expected in ("탐색", "승인", "화면"):
        assert expected in text
    for key in ("j/k", "Enter", "a", "?", "q"):
        assert key in text


def test_help_screen_filters_by_query():
    lines = _lines({"screen": "help", "query": "승인"})
    text = "\n".join(lines)
    assert "승인" in text
    assert "화면 전환" not in text


def test_help_screen_fits_all_contract_sizes():
    for size in ((60, 20), (80, 24), (120, 30), (160, 40)):
        for ln in _lines({"screen": "help"}, size=size):
            assert cell_width(ANSI.sub("", ln)) <= size[0]


# -- reconnect: guidance appears only while disconnected ----------------------

def test_daemon_down_shows_recovery_and_up_does_not():
    down = dict(SNAP, header=dict(SNAP["header"], daemon_up=False))
    down_text = "\n".join(workbench.render(down, workbench.initial_state(),
                                           (100, 30), color=False))
    up_text = "\n".join(_lines(size=(100, 30)))
    assert "복구:" in down_text
    assert "복구:" not in up_text
