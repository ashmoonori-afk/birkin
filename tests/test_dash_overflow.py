"""/dash body sizing: the overflow indicator, and reaching the last row.

Three different line counts were in play. `render` sized the body slot as
``rows - 5``, `_loop` clamped the cursor against ``rows - 6``, and
`_table_lines` treated the number it was handed as *data rows* while also
emitting a column header and an overflow indicator. So it built ``height + 2``
lines into a ``height``-line slot and `render` truncated the last two — which
happened to be the final row and the "↓ 더 있음" indicator that says the list
continues.

These tests pin the accounting rather than the arithmetic: every row is either
on screen or announced, and the cursor is always visible.
"""

from __future__ import annotations

import pytest

from birkin import dash


def _snap(n_sessions: int):
    return {
        "header": {"model": "claude-sonnet-4-6", "provider": "anthropic"},
        "sessions": [{"title": f"SESSION-{i:04d}", "age": "1h",
                      "path": f"/tmp/s{i}.json"} for i in range(n_sessions)],
        "agents": [], "cron": [], "approvals": [], "zones": [],
    }


def _frame(n_sessions: int, rows_h: int, cursor: int = 0, top: int = 0):
    snap = _snap(n_sessions)
    state = {"section": "세션", "cursor": cursor, "top": top}
    dash._clamp_cursor(snap, state, dash._row_capacity(
        dash._body_h(rows_h), n_sessions))
    return snap, state, dash.render(snap, state, (100, rows_h))


def _visible_titles(frame) -> list[str]:
    """Session ids actually painted. Deliberately ASCII so the Korean column
    header ("대화  수정") can never be mistaken for a data row."""
    return [f"SESSION-{i:04d}" for i in range(10_000)
            if any(f"SESSION-{i:04d}" in line for line in frame)]


@pytest.mark.parametrize("rows_h", [10, 24, 40, 60])
def test_overflow_indicator_is_actually_painted(rows_h):
    """It was built and then truncated away at every terminal size."""
    _, _, frame = _frame(200, rows_h)
    assert any("더 있음" in line for line in frame), (
        f"rows={rows_h}: 200 sessions rendered with no sign there are more")


@pytest.mark.parametrize("rows_h", [10, 24, 40, 60])
def test_frame_never_exceeds_the_terminal(rows_h):
    _, _, frame = _frame(200, rows_h)
    assert len(frame) <= rows_h


def test_no_row_is_silently_dropped():
    """Either a row is on screen, or the indicator says how many there are."""
    _, _, frame = _frame(42, 24)
    shown = _visible_titles(frame)
    assert shown, "nothing rendered at all"
    indicator = [l for l in frame if "더 있음" in l]
    assert indicator, "rows were dropped with no indicator"
    assert "42" in indicator[0], f"indicator does not report the total: {indicator[0]!r}"


def test_last_row_is_reachable():
    """G jumps to the end. The end has to be on screen when it does."""
    n = 42
    snap = _snap(n)
    state = {"section": "세션", "cursor": n - 1, "top": 0}
    cap = dash._row_capacity(dash._body_h(24), n)
    dash._clamp_cursor(snap, state, cap)
    frame = dash.render(snap, state, (100, 24))
    assert any(f"SESSION-{n - 1:04d}" in line for line in frame), (
        "cursor on the last row but that row is not painted")


def test_cursor_visible_while_scrolling():
    """Walk the whole list one row at a time; the cursor may never fall off."""
    n = 40
    snap = _snap(n)
    state = {"section": "세션", "cursor": 0, "top": 0}
    for i in range(n):
        state["cursor"] = i
        cap = dash._row_capacity(dash._body_h(24), n)
        dash._clamp_cursor(snap, state, cap)
        frame = dash.render(snap, state, (100, 24))
        assert any(f"SESSION-{i:04d}" in line for line in frame), (
            f"cursor at row {i} scrolled out of view")


def test_no_indicator_when_everything_fits():
    _, _, frame = _frame(3, 40)
    assert not any("더 있음" in line for line in frame)
    assert len(_visible_titles(frame)) == 3


def test_empty_section_renders_the_placeholder():
    snap = _snap(0)
    state = {"section": "세션", "cursor": 0, "top": 0}
    frame = dash.render(snap, state, (100, 24))
    assert any("없음" in line for line in frame)
    assert not any("더 있음" in line for line in frame)


def test_tiny_terminal_does_not_crash():
    for rows_h in (5, 6, 7, 8):
        _, _, frame = _frame(50, rows_h)
        assert len(frame) <= max(rows_h, 8)   # floors clamp below ~8 rows


def test_chrome_height_matches_the_header_block():
    """_body_h hardcodes the chrome height; this fails loudly if a line is
    ever added to the header, instead of silently eating a row again."""
    snap = _snap(1)
    header = dash._header_lines(snap, 100)
    # header lines + separator, then a blank + the hint line at the bottom
    assert len(header) + 1 + 2 == dash._CHROME_H


def test_loop_and_render_agree_on_the_body_height():
    """The regression was three different numbers for one quantity."""
    for rows_h in (10, 24, 40):
        snap = _snap(1)
        state = {"section": "세션", "cursor": 0, "top": 0}
        frame = dash.render(snap, state, (100, rows_h))
        body_lines = len(frame) - dash._CHROME_H
        assert body_lines == dash._body_h(rows_h)
