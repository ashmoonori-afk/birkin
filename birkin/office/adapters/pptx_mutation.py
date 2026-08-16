from __future__ import annotations

import hashlib
from pathlib import Path

from ..errors import DocumentError, DocumentErrorCode
from ..package import clone_package
from .ooxml_surgery import package_parts, splice_fragmented_text
from .pptx_discovery import (
    drawing_nodes_within,
    media_target_consumers,
    shape_has_table,
)
from .pptx_evidence import verify_evidence
from .pptx_inventory import presentation_inventory, require_shape
from .pptx_relationships import parse_part, relationship_inventory
from .pptx_types import OperationEvidence, ShapeLocator, TableCellLocator

_MAX_MEDIA_BYTES = 100 * 1024 * 1024


def _write(
    source: Path,
    output: Path,
    parts: dict[str, bytes],
    digest: str,
    replacements: dict[str, bytes],
    operation: str,
) -> OperationEvidence:
    _ = clone_package(source, output, replacements)
    try:
        return verify_evidence(output, digest, parts, replacements, operation)
    except Exception:
        output.unlink(missing_ok=True)
        raise


def patch_shape_text(
    source: Path,
    output: Path,
    locator: ShapeLocator,
    value: str,
    *,
    expected_text: str | None = None,
    expected_source_sha256: str | None = None,
    operation: str = "text_update",
) -> tuple[OperationEvidence, str]:
    parts, digest = package_parts(source, expected_source_sha256)
    part_uri, shape_id = locator["part_uri"], locator["shape_id"]
    if not shape_id:
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "locate", "shape locator is invalid")
    xml, start, end, _block = require_shape(parts, part_uri, shape_id)
    if shape_has_table(parse_part(part_uri, xml), shape_id):
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "locate",
            "generic shape text patch cannot safely address table cells",
            details={"reason": "table_shape_requires_cell_locator"},
        )
    changed, previous = splice_fragmented_text(
        xml, start, end, value, expected_text=expected_text
    )
    evidence = _write(source, output, parts, digest, {part_uri: changed}, operation)
    return evidence, previous


def patch_table_cell(
    source: Path,
    output: Path,
    locator: TableCellLocator,
    value: str,
    *,
    expected_text: str | None = None,
    expected_source_sha256: str | None = None,
) -> tuple[OperationEvidence, str]:
    row_index = locator.get("row_index")
    column_index = locator.get("column_index")
    if isinstance(row_index, bool) or row_index < 0:
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "locate", "table row_index must be non-negative")
    if isinstance(column_index, bool) or column_index < 0:
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "locate", "table column_index must be non-negative")
    parts, digest = package_parts(source, expected_source_sha256)
    part_uri, shape_id = locator["part_uri"], locator["shape_id"]
    xml, shape_start, shape_end, _block = require_shape(parts, part_uri, shape_id)
    if not shape_has_table(parse_part(part_uri, xml), shape_id):
        raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND, "locate", "located shape is not a table")
    rows = drawing_nodes_within(xml, "tr", shape_start, shape_end)
    if row_index >= len(rows):
        raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND, "locate", "table row not found")
    row = rows[row_index]
    cells = drawing_nodes_within(xml, "tc", row.start, row.end)
    if column_index >= len(cells):
        raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND, "locate", "table cell not found")
    cell = cells[column_index]
    changed, previous = splice_fragmented_text(
        xml, cell.start, cell.end, value, expected_text=expected_text
    )
    evidence = _write(source, output, parts, digest, {part_uri: changed}, "table_cell_update")
    return evidence, previous


def _image_kind(data: bytes) -> str | None:
    signatures = (
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"\xff\xd8\xff", "jpeg"),
        (b"GIF87a", "gif"),
        (b"GIF89a", "gif"),
        (b"BM", "bmp"),
        (b"II*\x00", "tiff"),
        (b"MM\x00*", "tiff"),
    )
    return next((kind for signature, kind in signatures if data.startswith(signature)), None)


def replace_image(
    source: Path,
    output: Path,
    locator: ShapeLocator,
    image: bytes | Path,
    *,
    expected_media_sha256: str | None = None,
    expected_source_sha256: str | None = None,
) -> OperationEvidence:
    parts, digest = package_parts(source, expected_source_sha256)
    inventory = presentation_inventory(parts)
    matches = [item for item in inventory["images"] if item["part_uri"] == locator.get("part_uri") and item["shape_id"] == locator.get("shape_id")]
    if len(matches) != 1:
        code = DocumentErrorCode.NODE_NOT_FOUND if not matches else DocumentErrorCode.AMBIGUOUS_LOCATOR
        raise DocumentError(code, "locate", "embedded image shape is not unique")
    selected = matches[0]
    if selected["mode"] != "embedded" or selected["target_part"] is None:
        raise DocumentError(DocumentErrorCode.LOSSY_WRITE_BLOCKED, "apply", "linked or unresolved image replacement is blocked", details={"reason": "external_or_unresolved_media"})
    target = selected["target_part"]
    parsed_relationships = {
        name: parse_part(name, data)
        for name, data in parts.items()
        if name.endswith(".rels")
    }
    _, relations = relationship_inventory(parts, parsed_relationships)
    consumers = media_target_consumers(parts, relations, target)
    if len(consumers) != 1:
        raise DocumentError(DocumentErrorCode.LOSSY_WRITE_BLOCKED, "apply", "shared image replacement is blocked", details={"reason": "shared_media_target", "references": len(consumers)})
    original = parts.get(target)
    if original is None:
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "locate", "embedded image target is missing")
    replacement = image if isinstance(image, bytes) else image.read_bytes()
    if not replacement or len(replacement) > _MAX_MEDIA_BYTES:
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "apply", "replacement image size is invalid")
    expected_kind = target.rsplit(".", 1)[-1].lower().replace("jpg", "jpeg").replace("tif", "tiff")
    if _image_kind(replacement) != expected_kind:
        raise DocumentError(DocumentErrorCode.LOSSY_WRITE_BLOCKED, "apply", "replacement image encoding does not match the existing part", details={"reason": "content_type_change_required"})
    current_hash = hashlib.sha256(original).hexdigest()
    if expected_media_sha256 is not None and current_hash != expected_media_sha256:
        raise DocumentError(DocumentErrorCode.PRECONDITION_FAILED, "locate", "image no longer matches media hash precondition", details={"expected_sha256": expected_media_sha256, "actual_sha256": current_hash})
    return _write(source, output, parts, digest, {target: replacement}, "image_replace")
