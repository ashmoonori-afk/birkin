"""Regression coverage for the six verified /work TUI rendering gaps."""
from __future__ import annotations

from birkin import ui, workbench


SNAP = {
    "header": {"model": "test", "daemon_up": True},
    "approvals": [{"id": "a", "status": "pending", "title": "approval"}],
    "sessions": [],
    "agents": [],
    "cron": [],
    "goal": {},
    "errors": {},
}


class _QuitKeys:
    def read(self, _timeout):
        return "q"


def test_gap_1_frame_writer_erases_rows_below_short_frame(monkeypatch):
    written: list[str] = []
    monkeypatch.setattr(workbench, "_size", lambda: (40, 12))
    monkeypatch.setattr(workbench.sys.stdout, "flush", lambda: None)

    workbench._loop(None, SNAP, written.append, _QuitKeys(),
                    workbench.initial_state())

    assert "\x1b[0J" in "".join(written)


def test_gap_2_help_search_captures_text_backspace_and_escape():
    state = workbench.initial_state()

    assert workbench.update_help_search(state, "/")
    assert state["screen"] == "help" and state["query"] == ""
    assert workbench.update_help_search(state, "a")
    assert workbench.update_help_search(state, "b")
    assert workbench.update_help_search(state, "\x7f")
    assert state["query"] == "a"
    assert workbench.update_help_search(state, "esc")
    assert state["screen"] == "overview" and "query" not in state


def test_gap_3_selected_tool_row_has_visible_cursor_marker():
    messages = [{"role": "assistant", "content": [
        {"type": "tool_use", "id": "one", "name": "first", "input": {}},
        {"type": "tool_use", "id": "two", "name": "second", "input": {}},
    ]}]

    lines = workbench.render_session(messages, set(), 60, 10, color=False,
                                     tool_cursor=1)

    first = next(line for line in lines if "first" in line)
    second = next(line for line in lines if "second" in line)
    assert first.startswith("  ")
    assert second.startswith("> ")


def test_gap_4_ascii_mode_is_runtime_reachable_by_environment(monkeypatch):
    monkeypatch.setenv("BIRKIN_ASCII", "1")

    frame = "\n".join(workbench.render(
        SNAP, workbench.initial_state(), (120, 20), color=False,
    ))

    assert "│" not in frame
    assert "─" not in frame
    assert "> ! approval" in frame


def test_gap_5_ambiguous_width_mode_is_runtime_reachable(monkeypatch):
    monkeypatch.setenv("BIRKIN_AMBIGUOUS_WIDE", "1")

    assert ui.cell_width("◆") == 2
    frame = workbench.render(SNAP, workbench.initial_state(), (84, 20),
                             color=False)
    assert all(ui.cell_width(line) <= 84 for line in frame)


def _turns(count: int) -> list[dict]:
    return [{"role": "assistant", "content": [
        {"type": "text", "text": f"turn-{i}"},
    ]} for i in range(count)]


def test_gap_6_session_scrollback_uses_clamped_offset():
    messages = _turns(12)

    tail = workbench.render_session(messages, set(), 40, 4, color=False,
                                    scroll=0)
    older = workbench.render_session(messages, set(), 40, 4, color=False,
                                     scroll=4)
    clamped = workbench.render_session(messages, set(), 40, 4, color=False,
                                       scroll=999)

    assert any("turn-11" in line for line in tail)
    assert not any("turn-11" in line for line in older)
    assert any("turn-0" in line for line in clamped)
    assert len(tail) <= 4 and len(older) <= 4 and len(clamped) <= 4
