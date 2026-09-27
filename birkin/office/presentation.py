"""Korean presentation text for structured Office decisions."""

from __future__ import annotations

import re
from collections.abc import Sequence

from .preview_semantics import PreviewSummary

# The language-neutral location grammar written by preview_semantics and
# operation_targets. Anything else (for example a cell such as "Revenue!B2")
# is already readable and passes through unchanged.
_FIELD = re.compile(r"(docx|hwpx) field (.+)", re.DOTALL)
_PLACEHOLDER = re.compile(r"pptx slide (\d+) placeholder (\d+)")
_PARAGRAPH = re.compile(r"(docx|hwpx|pptx) (?:paragraph|slide_paragraph) (\d+)")
_EMPTY_VALUE = "(빈 값)"


def _location_label(location: str) -> str:
    if (match := _FIELD.fullmatch(location)) is not None:
        return f"{match.group(1).upper()} 필드 '{match.group(2)}'"
    if (match := _PLACEHOLDER.fullmatch(location)) is not None:
        return f"슬라이드 {match.group(1)} 개체 틀 {match.group(2)}"
    if (match := _PARAGRAPH.fullmatch(location)) is not None:
        return f"{match.group(1).upper()} {match.group(2)}번째 문단"
    return location


def format_preview_replacement(summary: PreviewSummary) -> str:
    """Render one trusted structured replacement for a Korean review surface."""
    return (
        f"{_location_label(summary['location'])} 변경: "
        f"{summary['before'] or _EMPTY_VALUE} → {summary['after'] or _EMPTY_VALUE}"
    )


def format_preview_replacements(summaries: Sequence[PreviewSummary]) -> str:
    """Render structured replacements without changing their stored contract."""
    return "\n".join(format_preview_replacement(summary) for summary in summaries)
