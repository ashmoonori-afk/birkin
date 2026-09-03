"""Terminal workspace cleanup and layout-budget contracts."""

from __future__ import annotations

from copy import deepcopy

import pytest

from birkin import ui
from birkin.workspace import render_terminal
from birkin.workspace.terminal_layout import compose_layout


PANEL_KEYS = (
    "tasks_runs",
    "approvals",
    "files_evidence",
    "sessions_history",
    "activity_logs",
    "cron",
    "memory_skills",
    "checkpoints_restore",
    "computer_use",
    "settings_status",
)


def _workspace() -> tuple[dict[str, object], dict[str, object]]:
    snapshot: dict[str, object] = {
        "cursor": 7,
        "conversation": [
            {"id": "m1", "kind": "user_message", "text": "hello 한글 👋"},
            {"id": "m2", "kind": "assistant_message", "text": "latest reply"},
        ],
        "composer": {"draft": "draft 한글", "can_send": True},
        "panels": [{"key": key, "label": key, "items": []} for key in PANEL_KEYS],
        "status": {"connection": "connected"},
    }
    view: dict[str, object] = {
        "active_panel": "approvals",
        "selected_item_id": None,
        "scroll_anchor": "m2",
    }
    return snapshot, view


@pytest.mark.parametrize("width", [40, 60, 100, 160])
def test_frame_is_cell_exact_bounded_and_does_not_mutate_view(width: int) -> None:
    snapshot, view = _workspace()
    original = deepcopy(view)

    lines = render_terminal(snapshot, view, (width, 20), color=False)

    assert lines
    assert len(lines) <= 20
    assert all(ui.cell_width(line) == width for line in lines)
    assert view == original


def test_header_has_real_cursor_and_no_duplicate_decorations() -> None:
    snapshot, view = _workspace()
    text = "\n".join(render_terminal(snapshot, view, (100, 20), color=False))

    assert "ledger 7" in text
    assert "Ledger (34)" not in text
    assert text.count("connected") == 1
    assert "Conversation" not in text
    assert "Panel · " not in text


def test_tabs_overflow_by_whole_tokens_and_keep_active_panel() -> None:
    snapshot, view = _workspace()

    for width in (40, 60, 100):
        lines = render_terminal(snapshot, view, (width, 20), color=False)
        tabs = next(line for line in lines if "[approvals]" in line)
        assert "…" not in tabs
        assert "+" in tabs
        assert "[approvals]" in tabs


def test_small_row_budget_keeps_header_and_hint() -> None:
    snapshot, view = _workspace()

    lines = render_terminal(snapshot, view, (60, 8), color=False)

    assert lines
    assert lines[0].startswith("Birkin · Approvals")
    assert lines[-1].strip() == "Tab · ↑/↓ · Enter · Esc"
    assert len(lines) <= 8
    assert all(ui.cell_width(line) == 60 for line in lines)


def test_compose_layout_budgets_for_latest_conversation_lines() -> None:
    frame = compose_layout(
        header="header",
        border="border",
        conversation=["oldest", "middle", "latest"],
        tabs="tabs",
        panel=["panel"],
        composer="composer",
        hints="hints",
        rows=8,
    )

    assert frame == [
        "header",
        "border",
        "latest",
        "border",
        "tabs",
        "panel",
        "composer",
        "hints",
    ]
