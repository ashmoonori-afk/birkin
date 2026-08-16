"""Bounded XLSX edits and explicit structural-operation refusals."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from ..errors import DocumentErrorCode
from ..package import clone_package
from .ooxml_surgery import package_parts
from .xlsx_edit_common import edit_error as _error
from .xlsx_edit_common import edit_receipt as _receipt
from .xlsx_edit_common import resolve_sheet as _sheet
from .xlsx_formula_patch import cell_blocks, formula_elements, patch_numeric_cell
from .xlsx_formula_policy import is_safe_formula
from .xlsx_inventory import build_inventory, parse
from .xlsx_types import EditReceipt, XlsxInventory

_CELL = re.compile(r"[A-Za-z]{1,3}[1-9][0-9]*")
_REFUSED = frozenset({"range", "table", "named_range", "comment", "merged_cells", "chart"})


def operation_capabilities() -> dict[str, dict[str, str]]:
    surgical = {
        "sheet": "existing_sheet_visibility_only",
        "cell": "existing_finite_numeric_value_only",
        "formula": "normal_formula_text_only_cache_marked_stale",
        "style": "existing_cell_xf_only",
        "hidden_row": "existing_row_record_only",
        "hidden_column": "existing_column_interval_only",
    }
    result = {name: {"state": "surgical", "reason": reason} for name, reason in surgical.items()}
    result.update({name: {"state": "refused", "reason": "dependency_graph_update_not_proven"} for name in _REFUSED})
    return result


def operation_inventory(source: Path) -> XlsxInventory:
    parts, _ = package_parts(source, None)
    return build_inventory(parts)


def _locator(value: Mapping[str, object], *, cell: bool) -> tuple[str, str | None, str | None, str | None]:
    sheet = value.get("sheet")
    reference = value.get("cell") if cell else None
    if not isinstance(sheet, str) or not sheet:
        raise _error(DocumentErrorCode.INVALID_INPUT, "locate", "locator requires a sheet name")
    if cell and (not isinstance(reference, str) or _CELL.fullmatch(reference) is None):
        raise _error(DocumentErrorCode.INVALID_INPUT, "locate", "locator requires a valid cell reference")
    part = value.get("part_uri")
    sheet_id = value.get("sheet_id")
    if part is not None and not isinstance(part, str):
        raise _error(DocumentErrorCode.INVALID_INPUT, "locate", "part_uri must be a string")
    if sheet_id is not None and not isinstance(sheet_id, str):
        raise _error(DocumentErrorCode.INVALID_INPUT, "locate", "sheet_id must be a string")
    return sheet, reference.upper() if isinstance(reference, str) else None, part, sheet_id


def _cell_reference(locator: Mapping[str, object]) -> str:
    _, reference, _, _ = _locator(locator, cell=True)
    if reference is None:
        raise _error(DocumentErrorCode.INVALID_INPUT, "locate", "cell reference is required")
    return reference


def _cell_block(xml: bytes, reference: str) -> tuple[int, int, bytes]:
    blocks = [
        (start, end, block)
        for _element, start, end, block in cell_blocks(xml, reference)
    ]
    if not blocks:
        raise _error(DocumentErrorCode.NODE_NOT_FOUND, "locate", "cell not found")
    if len(blocks) != 1:
        raise _error(DocumentErrorCode.AMBIGUOUS_LOCATOR, "locate", "cell reference is not unique", matches=len(blocks))
    return blocks[0]


def patch_formula(
    source: Path, output: Path, locator: Mapping[str, object], formula: str, *,
    expected_formula: str | None = None, expected_source_sha256: str | None = None,
) -> EditReceipt:
    legal = all(
        ord(char) in {9, 10, 13}
        or 0x20 <= ord(char) <= 0xD7FF
        or 0xE000 <= ord(char) <= 0xFFFD
        or 0x10000 <= ord(char) <= 0x10FFFF
        for char in formula
    )
    if not formula or not legal:
        raise _error(DocumentErrorCode.INVALID_INPUT, "apply", "formula must be non-empty legal XML text")
    if not is_safe_formula(formula):
        raise _error(
            DocumentErrorCode.POLICY_DENIED,
            "apply",
            "active XLSX formula mutation requires explicit hash-bound consent",
            operation="formula",
            reason="active_formula_consent_required",
        )
    parts, _ = package_parts(source, expected_source_sha256)
    native, xml = _sheet(parts, locator)
    reference = _cell_reference(locator)
    start, end, block = _cell_block(xml, reference)
    formulas = list(re.finditer(rb"<((?:[A-Za-z_][\w.-]*:)?f)\b([^>]*)>(.*?)</\1\s*>", block, re.DOTALL))
    semantic = formula_elements(xml, reference)
    if len(formulas) != 1 or len(semantic) != 1:
        raise _error(DocumentErrorCode.UNSUPPORTED_EDIT, "apply", "cell must contain one explicit SpreadsheetML formula")
    kind = semantic[0].attrib.get("t", "normal")
    if kind != "normal" or semantic[0].attrib.keys() & {"ref", "si"}:
        raise _error(DocumentErrorCode.LOSSY_WRITE_BLOCKED, "apply", "array and shared formula edits require dependency-wide updates", operation="formula", formula_type=kind)
    current = "".join(semantic[0].itertext())
    if expected_formula is not None and current != expected_formula:
        raise _error(DocumentErrorCode.PRECONDITION_FAILED, "locate", "formula no longer matches precondition", expected_formula=expected_formula, actual_formula=current)
    changed_block = block[: formulas[0].start(3)] + html.escape(formula, quote=False).encode() + block[formulas[0].end(3) :]
    part = native["part_uri"]
    _ = clone_package(source, output, {part: xml[:start] + changed_block + xml[end:]})
    return _receipt("formula", native, reference, part, stale=True)


def patch_style(
    source: Path, output: Path, locator: Mapping[str, object], style_id: int, *,
    expected_style: int | None = None, expected_source_sha256: str | None = None,
) -> EditReceipt:
    if isinstance(style_id, bool) or style_id < 0:
        raise _error(DocumentErrorCode.INVALID_INPUT, "apply", "style_id must be a non-negative integer")
    parts, _ = package_parts(source, expected_source_sha256)
    inventory = build_inventory(parts)
    valid_styles = {item.get("style_id") for item in inventory["styles"]}
    if style_id not in valid_styles:
        raise _error(DocumentErrorCode.PRECONDITION_FAILED, "apply", "style_id is not present in cellXfs", style_id=style_id)
    native, xml = _sheet(parts, locator)
    reference = _cell_reference(locator)
    start, end, block = _cell_block(xml, reference)
    opening_end = block.find(b">") + 1
    opening = block[:opening_end]
    match = re.search(rb"\bs\s*=\s*([\"'])([0-9]+)\1", opening)
    current = 0 if match is None else int(match.group(2))
    if expected_style is not None and current != expected_style:
        raise _error(DocumentErrorCode.PRECONDITION_FAILED, "locate", "cell style no longer matches precondition", expected_style=expected_style, actual_style=current)
    if match is None:
        changed_opening = opening[:-1] + f' s="{style_id}">'.encode()
    else:
        changed_opening = opening[: match.start(2)] + str(style_id).encode() + opening[match.end(2) :]
    part = native["part_uri"]
    changed = xml[:start] + changed_opening + block[opening_end:] + xml[end:]
    _ = clone_package(source, output, {part: changed})
    return _receipt("style", native, reference, part, stale=False)


def set_sheet_visibility(
    source: Path, output: Path, locator: Mapping[str, object], visibility: str, *,
    expected_source_sha256: str | None = None,
) -> EditReceipt:
    if visibility not in {"visible", "hidden", "veryHidden"}:
        raise _error(DocumentErrorCode.INVALID_INPUT, "apply", "invalid sheet visibility")
    parts, _ = package_parts(source, expected_source_sha256)
    native, _ = _sheet(parts, locator)
    inventory = build_inventory(parts)
    current = next(str(item.get("kind")) for item in inventory["sheets"] if item.get("name") == native["sheet"])
    if visibility != "visible" and current == "visible" and sum(item.get("kind") == "visible" for item in inventory["sheets"]) == 1:
        raise _error(DocumentErrorCode.LOSSY_WRITE_BLOCKED, "apply", "workbook must retain a visible sheet", operation="sheet")
    xml = parts["xl/workbook.xml"]
    _ = parse("xl/workbook.xml", xml)
    name_attr = re.compile(rb"\bname\s*=\s*([\"'])" + re.escape(native["sheet"].encode()) + rb"\1")
    matches = [match for match in re.finditer(rb"<(?:\w+:)?sheet\b[^>]*/\s*>", xml) if name_attr.search(match.group())]
    if len(matches) != 1:
        raise _error(DocumentErrorCode.AMBIGUOUS_LOCATOR, "locate", "sheet element is not unique")
    block = matches[0].group()
    state = re.search(rb"\s+state\s*=\s*([\"'])(?:visible|hidden|veryHidden)\1", block)
    if visibility == "visible":
        changed_block = block if state is None else block[: state.start()] + block[state.end() :]
    elif state is None:
        insert = block.rfind(b"/>")
        changed_block = block[:insert] + f' state="{visibility}"'.encode() + block[insert:]
    else:
        changed_block = block[: state.start()] + f' state="{visibility}"'.encode() + block[state.end() :]
    changed = xml[: matches[0].start()] + changed_block + xml[matches[0].end() :]
    _ = clone_package(source, output, {"xl/workbook.xml": changed})
    return _receipt("sheet", native, None, "xl/workbook.xml", stale=False)


def refuse(operation: str) -> None:
    raise _error(DocumentErrorCode.LOSSY_WRITE_BLOCKED, "apply", f"XLSX {operation} mutation requires unsupported dependency-wide updates", operation=operation, reason="dependency_graph_update_not_proven")


def apply_operation(source: Path, output: Path, operation: Mapping[str, object]) -> EditReceipt:
    kind = operation.get("type", operation.get("operation"))
    if not isinstance(kind, str):
        raise _error(DocumentErrorCode.INVALID_INPUT, "plan", "XLSX operation type is required")
    if kind in _REFUSED:
        refuse(kind)
    raw_locator = operation.get("locator")
    if not isinstance(raw_locator, Mapping):
        raise _error(DocumentErrorCode.INVALID_INPUT, "plan", "XLSX operation locator is required")
    locator: dict[str, object] = {}
    for key, item in cast("Mapping[object, object]", raw_locator).items():
        if not isinstance(key, str):
            raise _error(DocumentErrorCode.INVALID_INPUT, "plan", "XLSX locator keys must be strings")
        locator[key] = item
    if kind == "cell":
        native, _ = _sheet(package_parts(source, None)[0], locator)
        reference = _cell_reference(locator)
        _ = patch_numeric_cell(source, output, reference, operation.get("value"), expected_value=None, sheet_part=native["part_uri"], expected_source_sha256=None)
        return _receipt("cell", native, reference, native["part_uri"], stale=False)
    if kind == "formula":
        value = operation.get("value")
        if not isinstance(value, str):
            raise _error(DocumentErrorCode.INVALID_INPUT, "plan", "formula value must be a string")
        return patch_formula(source, output, locator, value)
    if kind == "style":
        value = operation.get("value")
        if not isinstance(value, int) or isinstance(value, bool):
            raise _error(DocumentErrorCode.INVALID_INPUT, "plan", "style value must be an integer")
        return patch_style(source, output, locator, value)
    if kind == "sheet":
        value = operation.get("value")
        if not isinstance(value, str):
            raise _error(DocumentErrorCode.INVALID_INPUT, "plan", "sheet visibility must be a string")
        return set_sheet_visibility(source, output, locator, value)
    if kind == "hidden_row":
        from .xlsx_visibility import set_row_hidden
        row, value = operation.get("row"), operation.get("value")
        if not isinstance(row, int) or isinstance(row, bool) or not isinstance(value, bool):
            raise _error(DocumentErrorCode.INVALID_INPUT, "plan", "hidden row requires integer row and boolean value")
        return set_row_hidden(source, output, locator, row, value)
    if kind == "hidden_column":
        from .xlsx_visibility import set_column_hidden
        minimum, maximum, value = operation.get("min"), operation.get("max"), operation.get("value")
        if any(not isinstance(bound, int) or isinstance(bound, bool) for bound in (minimum, maximum)) or not isinstance(value, bool):
            raise _error(DocumentErrorCode.INVALID_INPUT, "plan", "hidden column requires integer bounds and boolean value")
        return set_column_hidden(source, output, locator, cast("int", minimum), cast("int", maximum), value)
    raise _error(DocumentErrorCode.UNSUPPORTED_EDIT, "plan", "unknown XLSX operation", operation=kind)
