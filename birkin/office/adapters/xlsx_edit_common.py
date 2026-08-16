"""Shared sheet-aware XLSX edit location primitives."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from ..errors import DocumentError, DocumentErrorCode
from .xlsx_inventory import build_inventory
from .xlsx_types import EditReceipt


def edit_error(code: DocumentErrorCode, stage: str, message: str, **details: object) -> DocumentError:
    return DocumentError(code, stage, message, details=details)


def resolve_sheet(parts: Mapping[str, bytes], locator: Mapping[str, object]) -> tuple[dict[str, str], bytes]:
    name = locator.get("sheet")
    if not isinstance(name, str) or not name:
        raise edit_error(DocumentErrorCode.INVALID_INPUT, "locate", "locator requires a sheet name")
    expected_part, expected_id = locator.get("part_uri"), locator.get("sheet_id")
    if expected_part is not None and not isinstance(expected_part, str):
        raise edit_error(DocumentErrorCode.INVALID_INPUT, "locate", "part_uri must be a string")
    if expected_id is not None and not isinstance(expected_id, str):
        raise edit_error(DocumentErrorCode.INVALID_INPUT, "locate", "sheet_id must be a string")
    matches: list[dict[str, str]] = []
    for item in build_inventory(parts)["sheets"]:
        native_value = item.get("locator")
        if not isinstance(native_value, dict):
            continue
        native = cast("dict[object, object]", native_value)
        if all(isinstance(key, str) and isinstance(value, str) for key, value in native.items()) and native.get("sheet") == name:
            matches.append({str(key): str(value) for key, value in native.items()})
    if not matches:
        raise edit_error(DocumentErrorCode.NODE_NOT_FOUND, "locate", "worksheet not found")
    if len(matches) != 1:
        raise edit_error(DocumentErrorCode.AMBIGUOUS_LOCATOR, "locate", "worksheet name is not unique")
    native = matches[0]
    if expected_part is not None and native["part_uri"] != expected_part:
        raise edit_error(DocumentErrorCode.PRECONDITION_FAILED, "locate", "worksheet part no longer matches locator")
    if expected_id is not None and native["sheet_id"] != expected_id:
        raise edit_error(DocumentErrorCode.PRECONDITION_FAILED, "locate", "worksheet id no longer matches locator")
    xml = parts.get(native["part_uri"])
    if xml is None:
        raise edit_error(DocumentErrorCode.NODE_NOT_FOUND, "locate", "worksheet part not found")
    return native, xml


def edit_receipt(operation: str, native: dict[str, str], cell: str | None, part: str, *, stale: bool) -> EditReceipt:
    locator = dict(native)
    if cell is not None:
        locator["cell"] = cell
    return {
        "operation": operation, "locator": locator, "changed_parts": [part],
        "preservation": "untouched_parts_byte_identical", "recalculated": False,
        "cache_stale": stale,
    }
