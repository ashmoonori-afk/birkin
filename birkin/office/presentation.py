"""Korean presentation text for structured Office decisions."""

from __future__ import annotations

from collections.abc import Sequence

from .preview_semantics import PreviewSummary


def format_preview_replacement(summary: PreviewSummary) -> str:
    """Render one trusted structured replacement for a Korean review surface."""
    return (
        f"{summary['location']} 변경: "
        f"{summary['before']} → {summary['after']}"
    )


def format_preview_replacements(summaries: Sequence[PreviewSummary]) -> str:
    """Render structured replacements without changing their stored contract."""
    return "\n".join(format_preview_replacement(summary) for summary in summaries)
