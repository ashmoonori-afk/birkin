"""Semantic token registry: Python-owned design tokens for every surface.

Spec (docs/ui/DESIGN.md §tokens): 17 required semantic tokens, three candidate
visual directions, brand accent strictly separated from danger, ANSI derived
from the same hex source the WebUI consumes, and honest NO_COLOR behavior.
"""
from __future__ import annotations

import json
import re

from birkin import ui_tokens

HEX = re.compile(r"^#[0-9a-f]{6}$")

REQUIRED = (
    "surface", "surface_elevated", "text_primary", "text_muted", "accent",
    "running", "waiting_human", "waiting_dependency", "success", "warning",
    "failure", "evidence", "memory", "diff_add", "diff_remove", "focus",
    "selection")


def test_token_set_is_the_contract():
    assert ui_tokens.TOKENS == REQUIRED


def test_three_directions_each_cover_every_token():
    assert len(ui_tokens.PALETTES) >= 3
    for name, palette in ui_tokens.PALETTES.items():
        assert set(palette) == set(REQUIRED), name
        for token, value in palette.items():
            assert HEX.match(value), (name, token, value)


def test_default_palette_is_a_real_direction():
    assert ui_tokens.DEFAULT_PALETTE in ui_tokens.PALETTES


def test_accent_is_not_danger_in_any_direction():
    for name, palette in ui_tokens.PALETTES.items():
        assert palette["accent"] != palette["failure"], name
        assert palette["accent"] != palette["warning"], name


def test_diff_add_and_remove_differ_everywhere():
    for name, palette in ui_tokens.PALETTES.items():
        assert palette["diff_add"] != palette["diff_remove"], name


def test_uistate_color_roles_resolve_to_tokens():
    from birkin import uistate
    for state in uistate.UI_STATES:
        role = uistate.color_role(state)
        assert role in ui_tokens.TOKENS or role == "muted"
        # "muted" aliases text_muted for low-priority states
        assert ui_tokens.hex_for(role) is not None


def test_sgr_derives_from_hex_single_source():
    value = ui_tokens.hex_for("accent")
    assert value is not None
    r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
    assert ui_tokens.sgr("accent") == f"\x1b[38;2;{r};{g};{b}m"


def test_sgr_respects_no_color():
    assert ui_tokens.sgr("accent", color=False) == ""
    assert ui_tokens.sgr("failure", color=False) == ""


def test_unknown_token_never_emits_garbage():
    assert ui_tokens.hex_for("no_such_token") is None
    assert ui_tokens.sgr("no_such_token") == ""


def test_export_is_json_serializable_and_complete():
    payload = ui_tokens.to_json()
    parsed = json.loads(json.dumps(payload, ensure_ascii=False))
    assert parsed["palette"] == ui_tokens.DEFAULT_PALETTE
    assert set(parsed["tokens"]) == set(REQUIRED)
    for token, entry in parsed["tokens"].items():
        assert HEX.match(entry["hex"]), token
        assert entry["sgr"].startswith("\x1b[38;2;"), token
