"""Replay field and placeholder operations to prove their exact before values.

Structured previews key DOCX/HWPX/PPTX text by paragraph, so a field or
placeholder operation cannot be matched to a preview node. Planning instead
runs the same in-memory resolvers the approved apply step uses, in the same
order, so the approval shows exactly the text each operation replaces and any
refusal carries apply's own error code.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .adapters.docx_fields import patch_field_parts
from .adapters.hwpx_edit import apply_edits, field_edit
from .adapters.hwpx_model import scan_sections
from .adapters.hwpx_package import load_hwpx
from .adapters.ooxml_surgery import package_parts
from .adapters.pptx import placeholder_parts
from .adapters.pptx_inventory import presentation_inventory
from .errors import DocumentError, DocumentErrorCode
from .render_contract import MAX_PREVIEW_TEXT_BYTES

_DEFAULT_SLIDE_PART = "ppt/slides/slide1.xml"
_SLIDE_NUMBER = re.compile(r"ppt/slides/slide([1-9][0-9]*)\.xml")


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    """Language-neutral location and exact current text of one operation."""

    location: str
    before: str


def _precondition(message: str) -> DocumentError:
    return DocumentError(DocumentErrorCode.PRECONDITION_FAILED, "preview", message)


def _text(operation: Mapping[str, object], key: str) -> str:
    value = operation.get(key)
    if not isinstance(value, str):
        raise _precondition(f"operation {key} must be a string")
    return value


def _docx(
    path: Path, source_sha256: str, operations: Sequence[Mapping[str, object]]
) -> list[ResolvedTarget | None]:
    if not all("field" in operation for operation in operations):
        raise _precondition(
            "field and paragraph operations must be requested in separate jobs"
        )
    parts, _ = package_parts(path, source_sha256)
    targets: list[ResolvedTarget | None] = []
    for operation in operations:
        key = _text(operation, "field")
        _part, previous, _kind = patch_field_parts(
            parts, key, _text(operation, "value"), None
        )
        targets.append(ResolvedTarget(f"docx field {key}", previous))
    return targets


def _hwpx(
    path: Path, source_sha256: str, operations: Sequence[Mapping[str, object]]
) -> list[ResolvedTarget | None]:
    parts, _, _ = load_hwpx(path, source_sha256)
    targets: list[ResolvedTarget | None] = []
    for operation in operations:
        key = _text(operation, "field")
        edit = field_edit(scan_sections(parts), key, _text(operation, "value"), None)
        replacements, previous = apply_edits(parts, [edit])
        parts.update(replacements)
        targets.append(ResolvedTarget(f"hwpx field {key}", previous["field"]))
    return targets


def _slide_number(parts: dict[str, bytes], slide_part: str) -> int:
    ordered = [
        slide["part_uri"] for slide in presentation_inventory(parts)["slides"]
    ]
    if slide_part in ordered:
        return ordered.index(slide_part) + 1
    match = _SLIDE_NUMBER.fullmatch(slide_part)
    if match is None:
        raise DocumentError(
            DocumentErrorCode.NODE_NOT_FOUND, "locate", "slide part not found"
        )
    return int(match.group(1))


def _pptx(
    path: Path, source_sha256: str, operations: Sequence[Mapping[str, object]]
) -> list[ResolvedTarget | None]:
    parts, _ = package_parts(path, source_sha256)
    numbers: dict[str, int] = {}
    targets: list[ResolvedTarget | None] = []
    for operation in operations:
        raw_locator = operation.get("locator")
        location = (
            cast("Mapping[str, object]", raw_locator)
            if isinstance(raw_locator, Mapping)
            else operation
        )
        slide_part = location.get("slide_part", _DEFAULT_SLIDE_PART)
        index = location.get("placeholder_idx")
        if (
            not isinstance(slide_part, str)
            or not isinstance(index, int)
            or isinstance(index, bool)
        ):
            raise _precondition("PPTX placeholder operation is malformed")
        if slide_part not in numbers:
            numbers[slide_part] = _slide_number(parts, slide_part)
        changed, previous, _block = placeholder_parts(
            parts, slide_part, index, _text(operation, "value"), None
        )
        parts[slide_part] = changed
        targets.append(
            ResolvedTarget(
                f"pptx slide {numbers[slide_part]} placeholder {index}", previous
            )
        )
    return targets


def needs_replay(
    format_name: str, operations: Sequence[Mapping[str, object]]
) -> bool:
    """Whether any operation is proven by replay rather than by preview nodes."""
    if format_name == "docx":
        return any("field" in operation for operation in operations)
    return format_name in {"hwpx", "pptx"}


def resolve_operation_targets(
    path: Path,
    format_name: str,
    source_sha256: str,
    operations: Sequence[Mapping[str, object]],
) -> list[ResolvedTarget | None]:
    """Return one exact target per operation, or None where preview nodes apply."""
    if not needs_replay(format_name, operations):
        return [None] * len(operations)
    if format_name == "docx":
        targets = _docx(path, source_sha256, operations)
    elif format_name == "hwpx":
        targets = _hwpx(path, source_sha256, operations)
    else:
        targets = _pptx(path, source_sha256, operations)
    before_bytes = sum(
        len(target.before.encode("utf-8")) for target in targets if target is not None
    )
    if before_bytes > MAX_PREVIEW_TEXT_BYTES:
        raise DocumentError(
            DocumentErrorCode.LIMIT_EXCEEDED,
            "preview",
            "resolved operation text exceeds the preview byte limit",
            details={"maximum": MAX_PREVIEW_TEXT_BYTES},
        )
    return targets


__all__ = ["ResolvedTarget", "needs_replay", "resolve_operation_targets"]
