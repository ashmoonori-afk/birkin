"""Read-only inventory for stable XLSX operation locators."""

from __future__ import annotations

import posixpath
from collections.abc import Iterator, Mapping
from typing import Protocol, cast

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from ..errors import DocumentError, DocumentErrorCode
from .xlsx_types import InventoryRecord, XlsxInventory


class Element(Protocol):
    tag: str
    attrib: dict[str, str]
    text: str | None

    def iter(self) -> Iterator[Element]: ...
    def itertext(self) -> Iterator[str]: ...
    def __iter__(self) -> Iterator[Element]: ...


def local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def attribute(element: Element, name: str) -> str | None:
    return next((value for key, value in element.attrib.items() if local(key) == name), None)


def parse(name: str, data: bytes) -> Element:
    try:
        return ElementTree.fromstring(data, forbid_dtd=True)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID,
            "inspect",
            f"malformed or namespace-unbound XML part: {name}",
            details={"part_uri": name},
        ) from exc


def relationship_source(name: str) -> str | None:
    directory, filename = posixpath.split(name)
    if not directory.endswith("/_rels") or not filename.endswith(".rels"):
        return None
    return posixpath.join(directory[:-6], filename[:-5])


def resolved_target(source: str, target: str) -> str:
    if target.startswith("/"):
        return posixpath.normpath(target[1:])
    return posixpath.normpath(posixpath.join(posixpath.dirname(source), target))


def relationships(parsed: Mapping[str, Element]) -> dict[str, dict[str, tuple[str, str]]]:
    result: dict[str, dict[str, tuple[str, str]]] = {}
    for name, root in parsed.items():
        source = relationship_source(name)
        if source is None:
            continue
        entries: dict[str, tuple[str, str]] = {}
        for item in root:
            identifier, target = attribute(item, "Id"), attribute(item, "Target")
            mode = (attribute(item, "TargetMode") or "Internal").lower()
            if identifier and target and mode != "external":
                entries[identifier] = (resolved_target(source, target), attribute(item, "Type") or "")
        result[source] = entries
    return result


def sheet_records(parsed: Mapping[str, Element], rels: Mapping[str, dict[str, tuple[str, str]]]) -> list[InventoryRecord]:
    workbook = parsed.get("xl/workbook.xml")
    if workbook is None:
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "inspect", "XLSX workbook part is missing")
    records: list[InventoryRecord] = []
    for sheet in (item for item in workbook.iter() if local(item.tag) == "sheet"):
        identifier = attribute(sheet, "id") or ""
        target = rels.get("xl/workbook.xml", {}).get(identifier, ("", ""))[0]
        records.append({
            "locator": {"sheet": attribute(sheet, "name") or "", "sheet_id": attribute(sheet, "sheetId") or "", "part_uri": target},
            "name": attribute(sheet, "name") or "", "part_uri": target,
            "kind": attribute(sheet, "state") or "visible",
        })
    return records


def _cell_storage(cell: Element, formula: Element | None) -> str:
    if formula is not None:
        return "formula"
    return {"s": "shared_string", "inlineStr": "inline_string", "d": "date", "e": "error", "b": "boolean", "str": "string"}.get(attribute(cell, "t") or "", "number")


def _sheet_inventory(
    root: Element, sheet: InventoryRecord, result: XlsxInventory,
    shared_strings: list[str],
) -> None:
    locator_value = sheet["locator"]
    if not isinstance(locator_value, dict):
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "inspect", "invalid internal sheet locator")
    locator = cast("dict[str, object]", locator_value)
    sheet_name, sheet_id, part_uri = locator.get("sheet"), locator.get("sheet_id"), locator.get("part_uri")
    if not isinstance(sheet_name, str) or not isinstance(sheet_id, str) or not isinstance(part_uri, str):
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "inspect", "incomplete internal sheet locator")
    base = {"sheet": sheet_name, "sheet_id": sheet_id, "part_uri": part_uri}
    for item in root.iter():
        kind = local(item.tag)
        if kind == "c":
            formula = next((child for child in item if local(child.tag) == "f"), None)
            value = next((child for child in item if local(child.tag) in {"v", "t"}), None)
            storage = _cell_storage(item, formula)
            raw_value = None if value is None else "".join(value.itertext())
            display_value = raw_value
            if storage == "shared_string" and raw_value is not None and raw_value.isdigit():
                index = int(raw_value)
                display_value = shared_strings[index] if index < len(shared_strings) else None
            record: InventoryRecord = {
                "locator": {**base, "cell": attribute(item, "r") or ""},
                "storage": storage, "value": display_value, "raw_value": raw_value,
                "style_id": int(style) if (style := attribute(item, "s")) and style.isdigit() else None,
            }
            if formula is not None:
                record["formula"] = "".join(formula.itertext())
                record["formula_type"] = attribute(formula, "t") or "normal"
            result["cells"].append(record)
        elif kind == "mergeCell":
            result["merged_cells"].append({"locator": base, "reference": attribute(item, "ref") or ""})
        elif kind == "autoFilter":
            result["ranges"].append({"locator": base, "kind": "auto_filter", "reference": attribute(item, "ref") or ""})
        elif kind == "row" and (attribute(item, "hidden") or "").lower() in {"1", "true"}:
            result["hidden_rows"].append({"locator": base, "reference": attribute(item, "r") or "", "hidden": True})
        elif kind == "col" and (attribute(item, "hidden") or "").lower() in {"1", "true"}:
            minimum, maximum = attribute(item, "min") or "0", attribute(item, "max") or "0"
            result["hidden_columns"].append({"locator": base, "min": int(minimum), "max": int(maximum), "hidden": True})


def build_inventory(parts: Mapping[str, bytes]) -> XlsxInventory:
    parsed = {name: parse(name, data) for name, data in parts.items() if name.lower().endswith((".xml", ".rels"))}
    rels = relationships(parsed)
    sheets = sheet_records(parsed, rels)
    result: XlsxInventory = {
        "sheets": sheets, "cells": [], "ranges": [], "tables": [],
        "named_ranges": [], "styles": [], "comments": [], "merged_cells": [],
        "hidden_rows": [], "hidden_columns": [], "drawings": [],
    }
    shared_root = parsed.get("xl/sharedStrings.xml")
    shared_strings = [] if shared_root is None else [
        "".join(item.itertext()) for item in shared_root if local(item.tag) == "si"
    ]
    part_to_sheet = {str(item.get("part_uri", "")): item for item in sheets}
    owner_by_part: dict[str, object] = {}
    for part, sheet in part_to_sheet.items():
        if part in parsed:
            _sheet_inventory(parsed[part], sheet, result, shared_strings)
        locator = sheet.get("locator")
        if isinstance(locator, dict):
            owner_by_part[part] = locator
            for target, _ in rels.get(part, {}).values():
                owner_by_part[target] = locator
    workbook = parsed["xl/workbook.xml"]
    names = [str(item.get("name", "")) for item in sheets]
    for item in (node for node in workbook.iter() if local(node.tag) == "definedName"):
        scope_id = attribute(item, "localSheetId")
        scope = names[int(scope_id)] if scope_id and scope_id.isdigit() and int(scope_id) < len(names) else None
        result["named_ranges"].append({"name": attribute(item, "name") or "", "scope": scope, "reference": "".join(item.itertext()), "part_uri": "xl/workbook.xml"})
    for name, root in parsed.items():
        if name.startswith("xl/tables/"):
            result["tables"].append({"locator": owner_by_part.get(name, {"part_uri": name}), "name": attribute(root, "name") or attribute(root, "displayName") or "", "reference": attribute(root, "ref") or "", "part_uri": name})
        elif "/comments" in name.lower() and name.endswith(".xml"):
            comment_kind = "threaded" if "threadedcomments" in name.lower() else "legacy"
            for item in (node for node in root.iter() if local(node.tag) in {"comment", "threadedComment"}):
                result["comments"].append({"locator": owner_by_part.get(name, {"part_uri": name}), "kind": comment_kind, "reference": attribute(item, "ref") or "", "part_uri": name})
    styles = parsed.get("xl/styles.xml")
    if styles is not None:
        cell_xfs = next((item for item in styles.iter() if local(item.tag) == "cellXfs"), None)
        if cell_xfs is not None:
            result["styles"] = [{"style_id": index, "part_uri": "xl/styles.xml"} for index, _ in enumerate(cell_xfs)]
    for source, entries in rels.items():
        for identifier, (target, relation_type) in entries.items():
            relation_kind = relation_type.rsplit("/", 1)[-1]
            if relation_kind in {"chart", "image"}:
                result["drawings"].append({"locator": owner_by_part.get(source, {"part_uri": source}), "kind": relation_kind, "relationship_id": identifier, "part_uri": source, "target": target})
    return result
