"""Legacy re-export of the canonical workspace theme contract."""

from .workspace.theme import (
    DEFAULT_PALETTE,
    PALETTES,
    ROLES,
    ansi256,
    contract,
    contrast_ratio,
    sgr,
    sgr_background,
    web_variables,
)

__all__ = [
    "DEFAULT_PALETTE",
    "PALETTES",
    "ROLES",
    "ansi256",
    "contract",
    "contrast_ratio",
    "sgr",
    "sgr_background",
    "web_variables",
]
