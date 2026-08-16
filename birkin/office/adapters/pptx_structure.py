from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from ..errors import DocumentError, DocumentErrorCode
from ..package import clone_package
from .ooxml_surgery import element_blocks, package_parts
from .pptx_evidence import verify_evidence
from .pptx_inventory import presentation_inventory
from .pptx_types import OperationEvidence, SlideLocator

_PRESENTATION = "ppt/presentation.xml"
_MAX_SLIDE_EMU = 51_206_400


def _write(
    source: Path,
    output: Path,
    parts: dict[str, bytes],
    digest: str,
    changed: bytes,
    operation: str,
) -> OperationEvidence:
    replacements = {_PRESENTATION: changed}
    _ = clone_package(source, output, replacements)
    try:
        return verify_evidence(output, digest, parts, replacements, operation)
    except Exception:
        output.unlink(missing_ok=True)
        raise


def _requested_parts(order: Sequence[str | SlideLocator]) -> list[str]:
    requested: list[str] = []
    for item in order:
        requested.append(item if isinstance(item, str) else item["part_uri"])
    return requested


def reorder_slides(
    source: Path,
    output: Path,
    order: Sequence[str | SlideLocator],
    *,
    expected_source_sha256: str | None = None,
) -> OperationEvidence:
    parts, digest = package_parts(source, expected_source_sha256)
    xml = parts.get(_PRESENTATION)
    if xml is None:
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "locate", "presentation part is missing")
    current = presentation_inventory(parts)["slides"]
    current_parts = [item["part_uri"] for item in current]
    requested = _requested_parts(order)
    if len(requested) != len(set(requested)) or set(requested) != set(current_parts):
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "locate",
            "slide order must contain every current slide exactly once",
            details={"current": current_parts, "requested": requested},
        )
    if requested != current_parts and re.search(rb"<(?:p:)?sectionLst\b", xml):
        raise DocumentError(
            DocumentErrorCode.LOSSY_WRITE_BLOCKED,
            "apply",
            "slide reorder with sections is blocked",
            details={"reason": "section_boundary_rewrite_required"},
        )
    lists = element_blocks(xml, b"p:sldIdLst")
    if len(lists) != 1:
        code = DocumentErrorCode.PACKAGE_INVALID if not lists else DocumentErrorCode.AMBIGUOUS_LOCATOR
        raise DocumentError(code, "locate", "presentation slide identifier list is not unique")
    start, end, block = lists[0]
    opening_end = block.find(b">") + 1
    closing_start = block.rfind(b"</p:sldIdLst")
    body = block[opening_end:closing_start]
    entries = list(re.finditer(rb"<p:sldId\b(?:[^>]*/>|.*?</p:sldId\s*>)", body, re.DOTALL))
    if len(entries) != len(current):
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "locate", "slide identifier list does not match the relationship graph")
    residue = body
    for entry in reversed(entries):
        residue = residue[: entry.start()] + residue[entry.end() :]
    if residue.strip():
        raise DocumentError(DocumentErrorCode.LOSSY_WRITE_BLOCKED, "apply", "slide list contains unknown children", details={"reason": "unknown_slide_list_content"})
    by_rid: dict[str, bytes] = {}
    for entry in entries:
        raw = entry.group()
        match = re.search(rb"\br:id\s*=\s*(['\"])(.*?)\1", raw)
        if match is None:
            raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "locate", "slide identifier has no relationship id")
        by_rid[match.group(2).decode("utf-8")] = raw
    part_to_rid = {item["part_uri"]: item["relationship_id"] for item in current}
    replacement_body = b"".join(by_rid[part_to_rid[part]] for part in requested)
    changed_block = block[:opening_end] + replacement_body + block[closing_start:]
    changed = xml[:start] + changed_block + xml[end:]
    return _write(source, output, parts, digest, changed, "slide_reorder")


def _replace_attribute(opening: bytes, name: bytes, value: int) -> bytes:
    pattern = rb"\b" + re.escape(name) + rb"\s*=\s*(['\"])(.*?)\1"
    found = list(re.finditer(pattern, opening))
    if len(found) != 1:
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "locate", f"slide size {name.decode()} attribute is not unique")
    match = found[0]
    return opening[: match.start(2)] + str(value).encode("ascii") + opening[match.end(2) :]


def set_slide_size(
    source: Path,
    output: Path,
    width_emu: int,
    height_emu: int,
    *,
    expected_source_sha256: str | None = None,
) -> OperationEvidence:
    for name, value in (("width_emu", width_emu), ("height_emu", height_emu)):
        if isinstance(value, bool) or not 1 <= value <= _MAX_SLIDE_EMU:
            raise DocumentError(DocumentErrorCode.INVALID_INPUT, "apply", f"{name} must be an OOXML EMU dimension between 1 and {_MAX_SLIDE_EMU}")
    parts, digest = package_parts(source, expected_source_sha256)
    xml = parts.get(_PRESENTATION)
    if xml is None:
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "locate", "presentation part is missing")
    if len(element_blocks(xml, b"p:presentation")) != 1:
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "locate", "presentation root is malformed")
    matches = list(re.finditer(rb"<p:sldSz\b[^>]*?/?>", xml))
    if len(matches) != 1:
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "locate", "presentation slide size declaration is not unique")
    match = matches[0]
    opening = _replace_attribute(match.group(), b"cx", width_emu)
    opening = _replace_attribute(opening, b"cy", height_emu)
    changed = xml[: match.start()] + opening + xml[match.end() :]
    return _write(source, output, parts, digest, changed, "slide_size_update")
