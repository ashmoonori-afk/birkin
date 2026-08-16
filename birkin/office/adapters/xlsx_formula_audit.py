"""Read-only, non-evaluating XLSX formula and calculation-state audit."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TypedDict

from ..typing_compat import NotRequired
from .xlsx_types import Element


class FormulaCell(TypedDict):
    sheet: str
    sheet_part: str
    cell: str
    formula_text: str
    formula_type: str
    shared_index: str | None
    formula_range: str | None
    cache_present: bool
    cache_type: str
    cache_value: str | None
    cache_error: str | None
    cache_status: str
    in_calculation_chain: bool


class ChainEntry(TypedDict):
    sheet: str | None
    sheet_index: int | None
    cell: str
    new_dependency_level: NotRequired[bool]
    child_chain: NotRequired[bool]


class DynamicArray(TypedDict):
    sheet: str
    sheet_part: str
    cell: str
    formula_text: str
    formula_range: str | None
    reason: str

class ExternalFormula(TypedDict):
    sheet: str
    sheet_part: str
    cell: str
    formula_text: str


class FormulaAudit(TypedDict):
    scope: str
    mathematical_correctness: str
    cache_freshness: str
    cells: list[FormulaCell]
    error_cells: list[FormulaCell]
    calculation_properties: dict[str, object]
    workbook_version: dict[str, str | None]
    calculation_chain: dict[str, object]
    dynamic_arrays: list[DynamicArray]
    future_functions: list[DynamicArray]
    direct_self_references: list[dict[str, str]]
    external_links: dict[str, object]


_EXTERNAL_FORMULA = re.compile(r"\[[^\]\r\n]+\][^!\r\n]*!")
_FUTURE_FUNCTION = re.compile(r"(?:_xlfn\.|_xlws\.)", re.IGNORECASE)
_DATA_PART = re.compile(
    r"xl/(?:externalLinks/[^/]+\.xml|connections\.xml|queryTables/[^/]+\.xml)"
)


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _attribute(element: Element, local_name: str) -> str | None:
    return next(
        (value for name, value in element.attrib.items() if _local(name) == local_name),
        None,
    )


def _boolean(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.lower() in {"1", "true"}

def _optional_attribute(element: Element | None, name: str) -> str | None:
    return None if element is None else _attribute(element, name)


def _sheet_names(sheet_inventory: Sequence[Mapping[str, object]]) -> dict[str, str]:
    return {
        part: str(item.get("name", ""))
        for item in sheet_inventory
        if isinstance((part := item.get("sheet_part")), str)
    }


def _chain(
    parsed: Mapping[str, Element], sheet_inventory: Sequence[Mapping[str, object]]
) -> tuple[list[ChainEntry], set[tuple[str, str]]]:
    root = parsed.get("xl/calcChain.xml")
    if root is None:
        return [], set()
    sheet_names = [str(item.get("name", "")) for item in sheet_inventory]
    sheet_parts = [item.get("sheet_part") for item in sheet_inventory]
    index: int | None = None
    entries: list[ChainEntry] = []
    locations: set[tuple[str, str]] = set()
    for item in root.iter():
        if _local(item.tag) != "c":
            continue
        raw_index = _attribute(item, "i")
        if raw_index is not None and raw_index.isdigit():
            index = int(raw_index)
        cell = _attribute(item, "r") or ""
        valid = index is not None and 1 <= index <= len(sheet_names)
        entry: ChainEntry = {
            "sheet": sheet_names[index - 1] if valid and index is not None else None,
            "sheet_index": index,
            "cell": cell,
        }
        level = _boolean(_attribute(item, "l"))
        child = _boolean(_attribute(item, "a"))
        if level is not None:
            entry["new_dependency_level"] = level
        if child is not None:
            entry["child_chain"] = child
        entries.append(entry)
        if valid and index is not None and isinstance(sheet_parts[index - 1], str):
            locations.add((str(sheet_parts[index - 1]), cell))
    return entries, locations


def _cache(cell: Element) -> tuple[bool, str, str | None, str | None, str]:
    value_element = next((item for item in cell if _local(item.tag) == "v"), None)
    value = None if value_element is None else "".join(value_element.itertext())
    present = value_element is not None
    cell_type = _attribute(cell, "t") or "number"
    error = value if cell_type == "e" and present else None
    status = "missing" if not present else ("stored_error" if error is not None else "stored_unverified")
    return present, cell_type, value, error, status


def _formula_cells(
    parsed: Mapping[str, Element],
    sheet_inventory: Sequence[Mapping[str, object]],
    chain_locations: set[tuple[str, str]],
) -> tuple[list[FormulaCell], list[DynamicArray], list[DynamicArray], list[ExternalFormula]]:
    names = _sheet_names(sheet_inventory)
    cells: list[FormulaCell] = []
    dynamic: list[DynamicArray] = []
    future: list[DynamicArray] = []
    external: list[ExternalFormula] = []
    for part in sorted(names):
        root = parsed.get(part)
        if root is None:
            continue
        for cell in (item for item in root.iter() if _local(item.tag) == "c"):
            formula = next((item for item in cell if _local(item.tag) == "f"), None)
            if formula is None:
                continue
            location = _attribute(cell, "r") or ""
            text = "".join(formula.itertext())
            formula_type = _attribute(formula, "t") or "normal"
            present, cache_type, value, error, status = _cache(cell)
            record: FormulaCell = {
                "sheet": names[part], "sheet_part": part, "cell": location,
                "formula_text": text, "formula_type": formula_type,
                "shared_index": _attribute(formula, "si"),
                "formula_range": _attribute(formula, "ref"),
                "cache_present": present, "cache_type": cache_type,
                "cache_value": value, "cache_error": error, "cache_status": status,
                "in_calculation_chain": (part, location) in chain_locations,
            }
            cells.append(record)
            if _FUTURE_FUNCTION.search(text):
                future_record: DynamicArray = {
                    "sheet": names[part], "sheet_part": part, "cell": location,
                    "formula_text": text, "formula_range": record["formula_range"],
                    "reason": "future_function_or_dynamic_array",
                }
                future.append(future_record)
                if formula_type == "array":
                    dynamic.append(future_record)
            if _EXTERNAL_FORMULA.search(text):
                external.append({
                    "sheet": names[part], "sheet_part": part, "cell": location,
                    "formula_text": text,
                })
    return cells, dynamic, future, external


def audit_formula_parts(
    parsed: Mapping[str, Element],
    parts: Mapping[str, bytes],
    sheet_inventory: Sequence[Mapping[str, object]],
    external_relationships: Sequence[Mapping[str, object]],
) -> FormulaAudit:
    workbook = parsed["xl/workbook.xml"]
    calc = next((item for item in workbook.iter() if _local(item.tag) == "calcPr"), None)
    version = next((item for item in workbook.iter() if _local(item.tag) == "fileVersion"), None)
    entries, chain_locations = _chain(parsed, sheet_inventory)
    cells, dynamic, future, external = _formula_cells(parsed, sheet_inventory, chain_locations)
    direct_cycles = [
        {"sheet": cell["sheet"], "sheet_part": cell["sheet_part"],
         "cell": cell["cell"], "detection": "direct_self_reference"}
        for cell in cells
        if cell["cell"] in {match.group(0).replace("$", "") for match in re.finditer(
            r"(?<![A-Za-z0-9_])\$?[A-Za-z]{1,3}\$?[1-9][0-9]*", cell["formula_text"]
        )}
    ]
    return {
        "scope": "stored_package_only_no_evaluation", "mathematical_correctness": "not_verified",
        "cache_freshness": "not_verified",
        "cells": cells,
        "error_cells": [cell for cell in cells if cell["cache_error"] is not None],
        "calculation_properties": {
            "mode": _optional_attribute(calc, "calcMode"),
            "calculation_id": _optional_attribute(calc, "calcId"),
            "full_calculation_on_load": _boolean(_optional_attribute(calc, "fullCalcOnLoad")),
            "force_full_calculation": _boolean(_optional_attribute(calc, "forceFullCalc")),
            "calculate_on_save": _boolean(_optional_attribute(calc, "calcOnSave")),
        },
        "workbook_version": {
            "application": _optional_attribute(version, "appName"),
            "last_edited": _optional_attribute(version, "lastEdited"),
            "lowest_edited": _optional_attribute(version, "lowestEdited"),
            "build": _optional_attribute(version, "rupBuild"),
        },
        "calculation_chain": {"present": "xl/calcChain.xml" in parts, "entries": entries},
        "dynamic_arrays": dynamic, "future_functions": future,
        "direct_self_references": direct_cycles,
        "external_links": {
            "formula_cells": external,
            "relationships": [dict(item) for item in external_relationships],
            "package_parts": sorted(name for name in parts if _DATA_PART.fullmatch(name)),
            "refresh_performed": False, "network_accessed": False,
        },
    }
