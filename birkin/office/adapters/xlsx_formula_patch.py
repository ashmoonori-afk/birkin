"""Lossless XLSX numeric-cell surgery; formula cells are never rewritten."""

from __future__ import annotations

import html
import math
import re
from pathlib import Path

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from ..errors import DocumentError, DocumentErrorCode
from ..package import clone_package
from .ooxml_semantics import Element, name_is, semantic_nodes
from .ooxml_surgery import package_parts, require_one

_SPREADSHEETML_NAMESPACES = frozenset(
    {
        "",
        "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "http://purl.oclc.org/ooxml/spreadsheetml/main",
        "s",
    }
)

_CELL_REFERENCE = re.compile(r"\$?[A-Za-z]{1,3}\$?[1-9][0-9]*")
_RANGE_REFERENCE = re.compile(
    r"(\$?[A-Za-z]{1,3}\$?[1-9][0-9]*):(\$?[A-Za-z]{1,3}\$?[1-9][0-9]*)"
)


def _coordinate(reference: str) -> tuple[int, int]:
    match = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?([1-9][0-9]*)", reference)
    if match is None:  # pragma: no cover - callers validate references
        raise ValueError(reference)
    column = 0
    for char in match.group(1).upper():
        column = column * 26 + ord(char) - ord("A") + 1
    return column, int(match.group(2))


def _root(xml: bytes) -> Element:
    try:
        return ElementTree.fromstring(xml, forbid_dtd=True)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID, "locate", "worksheet XML is malformed"
        ) from exc


def cell_blocks(xml: bytes, cell: str) -> list[tuple[Element, int, int, bytes]]:
    """Return semantic SpreadsheetML cells paired with exact byte spans."""
    reference = cell.upper()
    return [
        (node.element, node.start, node.end, node.block)
        for node in semantic_nodes(xml)
        if name_is(node.element, _SPREADSHEETML_NAMESPACES, "c")
        and node.element.attrib.get("r", "").upper() == reference
    ]


def formula_elements(xml: bytes, cell: str) -> list[Element]:
    """Return semantic SpreadsheetML formulas directly owned by a cell."""
    formulas: list[Element] = []
    for element, _start, _end, _block in cell_blocks(xml, cell):
        formulas.extend(
            child
            for child in element
            if name_is(child, _SPREADSHEETML_NAMESPACES, "f")
        )
    return formulas


def _inside_array_range(xml: bytes, cell: str) -> bool:
    target_column, target_row = _coordinate(cell)
    for formula in _root(xml).iter():
        if not name_is(formula, _SPREADSHEETML_NAMESPACES, "f") or formula.attrib.get("t") != "array":
            continue
        reference = formula.attrib.get("ref")
        if reference is None:
            continue
        bounds = _RANGE_REFERENCE.fullmatch(reference)
        if bounds is None:
            continue
        start_column, start_row = _coordinate(bounds.group(1))
        end_column, end_row = _coordinate(bounds.group(2))
        if (
            min(start_column, end_column) <= target_column <= max(start_column, end_column)
            and min(start_row, end_row) <= target_row <= max(start_row, end_row)
        ):
            return True
    return False


def numeric_value(value: object) -> bytes:
    if isinstance(value, bool):
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "apply",
            "boolean values are not numeric XLSX values",
        )
    if isinstance(value, int):
        return str(value).encode("ascii")
    if isinstance(value, float) and math.isfinite(value):
        return repr(value).encode("ascii")
    raise DocumentError(
        DocumentErrorCode.UNSUPPORTED_EDIT,
        "apply",
        "only finite numeric XLSX values are supported",
    )


def patch_numeric_cell(
    source: Path,
    output: Path,
    cell: str,
    value: object,
    *,
    expected_value: str | None,
    sheet_part: str,
    expected_source_sha256: str | None,
) -> dict[str, object]:
    if _CELL_REFERENCE.fullmatch(cell) is None:
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "locate", "invalid cell reference")
    raw_value = numeric_value(value)
    parts, _ = package_parts(source, expected_source_sha256)
    xml = parts.get(sheet_part)
    if xml is None or re.fullmatch(r"xl/worksheets/sheet\d+\.xml", sheet_part) is None:
        raise DocumentError(
            DocumentErrorCode.NODE_NOT_FOUND, "locate", "worksheet part not found"
        )
    matches = [
        (sheet_part, start, end, block)
        for _element, start, end, block in cell_blocks(xml, cell)
    ]
    _, start, _, block = require_one(matches, "XLSX cell reference")
    if formula_elements(xml, cell):
        raise DocumentError(
            DocumentErrorCode.LOSSY_WRITE_BLOCKED,
            "apply",
            "formula cells cannot be patched without invalidating their cached value",
        )
    if _inside_array_range(xml, cell.upper()):
        raise DocumentError(
            DocumentErrorCode.LOSSY_WRITE_BLOCKED,
            "apply",
            "array formula range dependents cannot be patched independently",
        )
    opening = block[: block.find(b">") + 1]
    cell_type = re.search(rb"\bt\s*=\s*([\"'])(.*?)\1", opening)
    if cell_type is not None and cell_type.group(2) != b"n":
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "apply",
            "only existing numeric cells support surgical value edits",
        )
    values = list(re.finditer(
        rb"<((?:[A-Za-z_][\w.-]*:)?v)(?:\s[^>]*)?>(.*?)</\1\s*>", block, re.DOTALL
    ))
    if len(values) != 1:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "apply",
            "cell must contain exactly one cached numeric value",
        )
    current = html.unescape(values[0].group(2).decode("utf-8"))
    if expected_value is not None and current != expected_value:
        raise DocumentError(
            DocumentErrorCode.PRECONDITION_FAILED,
            "locate",
            "cell value no longer matches adapter precondition",
            details={"expected_value": expected_value, "actual_value": current},
        )
    value_start, value_end = start + values[0].start(2), start + values[0].end(2)
    changed = xml[:value_start] + raw_value + xml[value_end:]
    _ = clone_package(source, output, {sheet_part: changed})
    return {"calculated": False, "cell": cell, "source_part": sheet_part}
