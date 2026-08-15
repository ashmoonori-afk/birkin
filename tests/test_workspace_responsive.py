"""Responsive view-state contracts shared by terminal and web."""

from __future__ import annotations

from pathlib import Path

from birkin.workspace import render_terminal

HTML_PATH = (
    Path(__file__).resolve().parents[1]
    / "birkin"
    / "web"
    / "static"
    / "index.html"
)


def test_terminal_render_preserves_focus_scroll_and_draft_inputs() -> None:
    snapshot: dict[str, object] = {
        "conversation": (
            {"kind": "user_message", "text": "폭 테스트 한글", "id": "m1"},
        ),
        "composer": {"draft": "draft-sentinel", "can_send": True},
        "panels": (
            {"key": "tasks_runs", "label": "tasks_runs", "items": ()},
            {"key": "approvals", "label": "approvals", "items": ()},
        ),
    }
    view: dict[str, object] = {
        "active_panel": "approvals",
        "selected_item_id": "approval-1",
        "scroll_anchor": "m1",
    }
    original = dict(view)

    for size in ((60, 20), (100, 30), (160, 40)):
        lines = render_terminal(snapshot, view, size, color=False)
        assert lines
        assert view == original


def test_mobile_sheet_has_explicit_back_and_escape_contract() -> None:
    source = HTML_PATH.read_text(encoding="utf-8")

    assert 'data-testid="workspace-mobile-back"' in source
    assert 'aria-controls="workspace-panel"' in source
    assert 'event.key === "Escape"' in source
    assert 'shell.dataset.panelOpen = "false"' in source


def test_responsive_transitions_preserve_composer_draft() -> None:
    source = HTML_PATH.read_text(encoding="utf-8")

    assert "birkin.workspace.draft" in source
    assert "localStorage.setItem" in source
    assert "localStorage.getItem" in source
    assert "@media (max-width: 820px)" in source
    assert "prefers-reduced-motion" in source
