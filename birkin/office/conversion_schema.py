"""Dependency-free conversion loss-budget schema."""

from __future__ import annotations

from typing import Final

LOSS_CATEGORIES: Final[tuple[str, ...]] = (
    "structure",
    "style_layout",
    "formula_cache",
    "chart_media",
    "macro_active_content",
    "tracked_changes_comments",
    "form_field",
    "metadata",
    "signature_encryption",
    "accessibility",
)


def budget_schema() -> dict[str, object]:
    """JSON schema for explicit conversion loss budgets."""
    return {
        "type": "object",
        "description": (
            "Maximum observed losses by category; omitted categories require "
            "lossless preservation."
        ),
        "properties": {
            category: {"type": "integer", "minimum": 0}
            for category in LOSS_CATEGORIES
        },
        "additionalProperties": False,
    }
