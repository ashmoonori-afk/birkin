"""Surgical edits of existing XLSX row and column visibility records."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from ..errors import DocumentError, DocumentErrorCode
from ..package import clone_package
from .ooxml_surgery import package_parts
from .xlsx_edit_common import edit_receipt, resolve_sheet
from .xlsx_inventory import parse
from .xlsx_types import EditReceipt


def _hidden(block: bytes, hidden: bool) -> bytes:
    match = re.search(rb"\s+hidden\s*=\s*([\"'])(?:0|1|true|false)\1", block, re.IGNORECASE)
    if match is not None:
        value = b' hidden="1"' if hidden else b' hidden="0"'
        return block[: match.start()] + value + block[match.end() :]
    end = block.find(b">")
    if end < 0:
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "apply", "malformed visibility target")
    return block[:end] + (b' hidden="1"' if hidden else b' hidden="0"') + block[end:]


def _replace_one(xml: bytes, matches: list[re.Match[bytes]], hidden: bool, label: str) -> bytes:
    if not matches:
        raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND, "locate", f"{label} not found")
    if len(matches) != 1:
        raise DocumentError(DocumentErrorCode.AMBIGUOUS_LOCATOR, "locate", f"{label} is not unique")
    match = matches[0]
    return xml[: match.start()] + _hidden(match.group(), hidden) + xml[match.end() :]


def set_row_hidden(
    source: Path, output: Path, locator: Mapping[str, object], row: int, hidden: bool, *,
    expected_source_sha256: str | None = None,
) -> EditReceipt:
    if isinstance(row, bool) or row < 1:
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "apply", "row must be positive and hidden must be boolean")
    parts, _ = package_parts(source, expected_source_sha256)
    native, xml = resolve_sheet(parts, locator)
    _ = parse(native["part_uri"], xml)
    attr = re.compile(rb"\br\s*=\s*([\"'])" + str(row).encode() + rb"\1")
    matches = [item for item in re.finditer(rb"<(?:\w+:)?row\b[^>]*(?:/\s*>|>.*?</(?:\w+:)?row\s*>)", xml, re.DOTALL) if attr.search(item.group().split(b">", 1)[0])]
    changed = _replace_one(xml, matches, hidden, "row")
    part = native["part_uri"]
    _ = clone_package(source, output, {part: changed})
    receipt = edit_receipt("hidden_row", native, None, part, stale=False)
    receipt["locator"]["row"] = str(row)
    return receipt


def set_column_hidden(
    source: Path, output: Path, locator: Mapping[str, object], minimum: int, maximum: int,
    hidden: bool, *, expected_source_sha256: str | None = None,
) -> EditReceipt:
    if any(isinstance(value, bool) or value < 1 for value in (minimum, maximum)) or minimum > maximum:
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "apply", "column bounds must be positive ordered integers and hidden must be boolean")
    parts, _ = package_parts(source, expected_source_sha256)
    native, xml = resolve_sheet(parts, locator)
    _ = parse(native["part_uri"], xml)
    minimum_attr = re.compile(rb"\bmin\s*=\s*([\"'])" + str(minimum).encode() + rb"\1")
    maximum_attr = re.compile(rb"\bmax\s*=\s*([\"'])" + str(maximum).encode() + rb"\1")
    matches = [item for item in re.finditer(rb"<(?:\w+:)?col\b[^>]*/\s*>", xml) if minimum_attr.search(item.group()) and maximum_attr.search(item.group())]
    changed = _replace_one(xml, matches, hidden, "column interval")
    part = native["part_uri"]
    _ = clone_package(source, output, {part: changed})
    receipt = edit_receipt("hidden_column", native, None, part, stale=False)
    receipt["locator"].update({"min": str(minimum), "max": str(maximum)})
    return receipt
