"""Shared semantic theme contracts for terminal ANSI and web CSS."""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

import pytest

from birkin.web import server as web_server
from birkin.workspace import render_terminal, theme

EXPECTED_ROLES = {
    "accent",
    "border",
    "border_accent",
    "border_muted",
    "text",
    "muted",
    "dim",
    "background",
    "surface",
    "surface_raised",
    "focus_ring",
    "success",
    "warning",
    "error",
    "info",
    "pending",
    "blocked",
    "action_needed",
    "selected_bg",
    "user_message_bg",
    "assistant_message_bg",
    "thinking_bg",
    "tool_pending_bg",
    "tool_success_bg",
    "tool_error_bg",
    "action_needed_bg",
    "evidence_bg",
    "composer_bg",
}

HTML_PATH = (
    Path(__file__).resolve().parents[1]
    / "birkin"
    / "web"
    / "static"
    / "index.html"
)


def test_all_palettes_and_terminal_adapters_cover_every_role() -> None:
    assert set(theme.ROLES) == EXPECTED_ROLES
    assert set(theme.PALETTES) == {
        "studio_dark",
        "paper_light",
        "high_contrast",
    }
    for palette in theme.PALETTES.values():
        assert set(palette) == EXPECTED_ROLES
    assert set(theme.ansi256("studio_dark")) == EXPECTED_ROLES
    assert all(
        0 <= index <= 255
        for index in theme.ansi256("studio_dark").values()
    )
    assert theme.sgr("accent", "studio_dark", color=False) == ""


def test_terminal_renderer_uses_truecolor_ansi256_and_no_color() -> None:
    snapshot: dict[str, object] = {
        "conversation": [],
        "composer": {"draft": "", "can_send": True},
        "panels": [
            {"key": "tasks_runs", "label": "Tasks", "items": []},
        ],
        "status": {"connection": "connected"},
    }
    view: dict[str, object] = {"active_panel": "tasks_runs"}

    truecolor = "\n".join(
        render_terminal(snapshot, view, (80, 20), color=True)
    )
    reduced = "\n".join(
        render_terminal(
            snapshot,
            view,
            (80, 20),
            color=True,
            ansi_256=True,
        )
    )
    plain = "\n".join(
        render_terminal(snapshot, view, (80, 20), color=False)
    )
    assert "\x1b[38;2;" in truecolor
    assert "\x1b[38;5;" in reduced
    assert "\x1b[" not in plain


@pytest.mark.parametrize(
    ("palette", "foreground", "background", "minimum"),
    [
        ("studio_dark", "text", "background", 7.0),
        ("studio_dark", "muted", "background", 4.5),
        ("paper_light", "text", "background", 7.0),
        ("paper_light", "muted", "background", 4.5),
        ("paper_light", "dim", "surface_raised", 4.5),
        ("paper_light", "border", "surface_raised", 3.0),
        ("high_contrast", "text", "background", 7.0),
        ("high_contrast", "accent", "background", 4.5),
    ],
)
def test_palette_contrast_relationships(
    palette: str,
    foreground: str,
    background: str,
    minimum: float,
) -> None:
    assert theme.contrast_ratio(
        theme.PALETTES[palette][foreground],
        theme.PALETTES[palette][background],
    ) >= minimum


def test_web_contract_exports_theme_and_static_css_uses_only_roles() -> None:
    contract = web_server.workspace_contract()
    exported = cast(dict[str, object], contract["workspace_theme"])
    assert set(cast(list[str], exported["roles"])) == EXPECTED_ROLES
    assert set(cast(dict[str, object], exported["palettes"])) == set(theme.PALETTES)

    source = HTML_PATH.read_text(encoding="utf-8")
    for role in EXPECTED_ROLES:
        assert f"--birkin-{role.replace('_', '-')}" in source
    assert "setProperty(`--${variable}`" in source
    assert re.search(r"#[0-9a-fA-F]{6}", source) is None
