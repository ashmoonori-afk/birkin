"""Semantic design tokens: Python-owned, exported to every surface.

Token names say why a color is used, never which color it is. Three candidate
visual directions live side by side; ``DEFAULT_PALETTE`` names the shipped
one. ANSI truecolor sequences are derived from the same hex the WebUI reads,
so there is exactly one color source. Callers gate emission with
:func:`birkin.ui.should_color`; ``sgr(..., color=False)`` is the NO_COLOR
path and returns an empty string.
"""
from __future__ import annotations

from typing import Any

TOKENS: tuple[str, ...] = (
    "surface", "surface_elevated", "text_primary", "text_muted", "accent",
    "running", "waiting_human", "waiting_dependency", "success", "warning",
    "failure", "evidence", "memory", "diff_add", "diff_remove", "focus",
    "selection")

# Aliases keep uistate color roles decoupled from raw token names.
_ALIASES: dict[str, str] = {"muted": "text_muted"}

# Three directions. State hues stay in the same family across directions so
# state meaning survives a palette switch; only surface mood and brand accent
# move. Accent is never the danger hue (enforced by tests).
PALETTES: dict[str, dict[str, str]] = {
    # 작업대(atelier): warm graphite + brass — a lit workbench, tools at hand.
    "atelier": {
        "surface": "#12100d", "surface_elevated": "#1b1813",
        "text_primary": "#ece5d8", "text_muted": "#8f8778",
        "accent": "#c9a227",
        "running": "#56a8d6", "waiting_human": "#cf7bc9",
        "waiting_dependency": "#7a8fb8", "success": "#86b25c",
        "warning": "#d98a45", "failure": "#d16969",
        "evidence": "#4db6ac", "memory": "#9d81c4",
        "diff_add": "#6a9955", "diff_remove": "#c74e39",
        "focus": "#e2c044", "selection": "#3a3527",
    },
    # 관측소(observatory): deep indigo + violet — night ops, high contrast.
    "observatory": {
        "surface": "#0d1021", "surface_elevated": "#161a33",
        "text_primary": "#e6e8f5", "text_muted": "#8a90b8",
        "accent": "#8b7ce0",
        "running": "#53b0d6", "waiting_human": "#e070b8",
        "waiting_dependency": "#6f87c9", "success": "#66bb8a",
        "warning": "#d8a04f", "failure": "#d95c5c",
        "evidence": "#45b8b0", "memory": "#a98fd6",
        "diff_add": "#5fa86a", "diff_remove": "#cc5a4a",
        "focus": "#d6c04f", "selection": "#263259",
    },
    # 옥(jade): graphite green + jade — calm, low-stimulus monitoring.
    "jade": {
        "surface": "#0e1412", "surface_elevated": "#17201c",
        "text_primary": "#e2ece7", "text_muted": "#85978e",
        "accent": "#4fb98a",
        "running": "#4da3c7", "waiting_human": "#cf7bc9",
        "waiting_dependency": "#6e93a8", "success": "#79b25f",
        "warning": "#d3a253", "failure": "#d4605f",
        "evidence": "#3fb3ad", "memory": "#a084cf",
        "diff_add": "#63a35c", "diff_remove": "#c65746",
        "focus": "#d9bd55", "selection": "#24352d",
    },
}

DEFAULT_PALETTE = "atelier"


def hex_for(token: str, palette: str | None = None) -> str | None:
    """Hex value for a token (or alias); ``None`` for unknown tokens."""
    name = _ALIASES.get(token, token)
    return PALETTES.get(palette or DEFAULT_PALETTE, {}).get(name)


def sgr(token: str, palette: str | None = None, *, color: bool = True) -> str:
    """Truecolor SGR escape derived from the hex source; "" when color is off."""
    if not color:
        return ""
    value = hex_for(token, palette)
    if value is None:
        return ""
    r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
    return f"\x1b[38;2;{r};{g};{b}m"


def to_json(palette: str | None = None) -> dict[str, Any]:
    """Full export for non-Python surfaces (WebUI reads this, never a copy)."""
    chosen = palette or DEFAULT_PALETTE
    return {
        "palette": chosen,
        "tokens": {
            token: {"hex": hex_for(token, chosen),
                    "sgr": sgr(token, chosen)}
            for token in TOKENS
        },
    }
