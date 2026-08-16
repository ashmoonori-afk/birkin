from __future__ import annotations

import posixpath
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Protocol, cast, final

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from ..errors import DocumentError, DocumentErrorCode
from ..package import preflight_package
from .xlsx_formula_audit import FormulaAudit, audit_formula_parts
from .xlsx_formula_patch import patch_numeric_cell
from .xlsx_operations import (
    apply_operation as _apply_operation,
)
from .xlsx_operations import (
    operation_capabilities as _operation_capabilities,
)
from .xlsx_operations import (
    operation_inventory as _operation_inventory,
)
from .xlsx_operations import (
    patch_formula as _patch_formula,
)
from .xlsx_operations import (
    patch_style as _patch_style,
)
from .xlsx_operations import (
    set_sheet_visibility as _set_sheet_visibility,
)
from .xlsx_visibility import set_column_hidden as _set_column_hidden
from .xlsx_visibility import set_row_hidden as _set_row_hidden

_EXTERNAL_FORMULA = re.compile(r"\[[^\]\r\n]+\][^!\r\n]*!")
_DDE_FORMULA = re.compile(r"\|[^!\r\n]*!")
class _Element(Protocol):
    tag: str
    attrib: dict[str, str]
    text: str | None
    def iter(self) -> Iterator[_Element]: ...
    def itertext(self) -> Iterator[str]: ...
    def __iter__(self) -> Iterator[_Element]: ...
def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]
def _parse_part(name: str, data: bytes) -> _Element:
    try:
        return ElementTree.fromstring(data, forbid_dtd=True)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID, "inspect", f"malformed or namespace-unbound XML part: {name}", details={"part_uri": name}
        ) from exc

def _attribute(element: _Element, local_name: str) -> str | None:
    return next(
        (value for name, value in element.attrib.items() if _local(name) == local_name),
        None,
    )

def _ranges(intervals: list[tuple[int, int]]) -> list[str]:
    merged: list[list[int]] = []
    for start, end in sorted(set(intervals)):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [str(start) if start == end else f"{start}:{end}" for start, end in merged]

def _internal_target(target: str) -> str:
    return posixpath.normpath(target[1:] if target.startswith("/") else posixpath.join("xl", target))

@final
class XlsxAdapter:
    format: str = "xlsx"
    operation_inventory = staticmethod(_operation_inventory)
    operation_capabilities = staticmethod(_operation_capabilities)
    apply_operation = staticmethod(_apply_operation)
    patch_formula = staticmethod(_patch_formula)
    patch_style = staticmethod(_patch_style)
    set_sheet_visibility = staticmethod(_set_sheet_visibility)
    set_row_hidden = staticmethod(_set_row_hidden)
    set_column_hidden = staticmethod(_set_column_hidden)
    def inspect(self, path: Path) -> dict[str, object]:
        manifest = preflight_package(path)
        parts = {name: item["bytes"] for name, item in manifest["parts"].items()}
        parsed = {
            name: _parse_part(name, data)
            for name, data in parts.items()
            if name.lower().endswith((".xml", ".rels"))
        }
        workbook = parsed.get("xl/workbook.xml")
        if workbook is None:
            raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "inspect", "XLSX workbook part is missing")
        relationship_parts: dict[str, str] = {}
        relationships = parsed.get("xl/_rels/workbook.xml.rels")
        if relationships is not None:
            for relation in relationships:
                if _attribute(relation, "TargetMode") not in {"External", "external"}:
                    identifier = _attribute(relation, "Id")
                    target = _attribute(relation, "Target")
                    if identifier and target:
                        relationship_parts[identifier] = _internal_target(target)
        sheet_inventory: list[dict[str, object]] = []
        for sheet in (item for item in workbook.iter() if _local(item.tag) == "sheet"):
            visibility = _attribute(sheet, "state") or "visible"
            if visibility not in {"visible", "hidden", "veryHidden"}:
                raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "inspect", "workbook contains an invalid sheet visibility")
            identifier = _attribute(sheet, "id")
            sheet_inventory.append(
                {
                    "name": _attribute(sheet, "name") or "",
                    "visibility": visibility,
                    "sheet_part": relationship_parts.get(identifier or ""),
                }
            )
        formula_risks: list[dict[str, object]] = []
        hidden_rows: list[dict[str, object]] = []
        hidden_columns: list[dict[str, object]] = []
        sheet_parts = sorted(
            name
            for name in parsed
            if re.fullmatch(r"xl/(?:worksheets|macrosheets)/[^/]+\.xml", name)
        )
        for name in sheet_parts:
            root = parsed[name]
            row_intervals = [
                (int(row.attrib["r"]), int(row.attrib["r"]))
                for row in root.iter()
                if _local(row.tag) == "row"
                and row.attrib.get("hidden", "").lower() in {"1", "true"}
                and row.attrib.get("r", "").isdigit()
            ]
            column_intervals = [
                (int(column.attrib["min"]), int(column.attrib["max"]))
                for column in root.iter()
                if _local(column.tag) == "col"
                and column.attrib.get("hidden", "").lower() in {"1", "true"}
                and column.attrib.get("min", "").isdigit()
                and column.attrib.get("max", "").isdigit()
            ]
            if row_intervals:
                hidden_rows.append({"sheet_part": name, "ranges": _ranges(row_intervals)})
            if column_intervals:
                hidden_columns.append({"sheet_part": name, "ranges": _ranges(column_intervals)})
        formula_audit = audit_formula_parts(
            parsed, parts, sheet_inventory, manifest["external_relationships"]
        )
        for cell in formula_audit["cells"]:
            text = cell["formula_text"]
            code = None
            if _DDE_FORMULA.search(text):
                code = "XLSX_DDE_FORMULA"
            elif _EXTERNAL_FORMULA.search(text):
                code = "XLSX_EXTERNAL_WORKBOOK_FORMULA"
            if code is not None:
                formula_risks.append({
                    "code": code, "sheet_part": cell["sheet_part"],
                    "cell": cell["cell"], "formula": text,
                })
        active_content: list[dict[str, object]] = [dict(item) for item in manifest["active_content"]]
        active_content.extend(
            {"part_uri": name, "kind": "xlm_macro"}
            for name in sheet_parts
            if name.startswith("xl/macrosheets/")
        )
        risk_codes: dict[object, str] = {
            "macro": "XLSX_VBA_PROJECT",
            "active_x": "XLSX_ACTIVEX",
            "embedded_object": "XLSX_EMBEDDED_OBJECT",
            "xlm_macro": "XLSX_XLM_MACRO_SHEET",
        }
        risks: list[dict[str, object]] = [
            {"code": risk_codes[item["kind"]], "part_uri": item["part_uri"]}
            for item in active_content
        ]
        risks.extend(formula_risks)
        risks.extend(
            {"code": "XLSX_EXTERNAL_RELATIONSHIP", **item}
            for item in manifest["external_relationships"]
        )
        worksheets = [name for name in sheet_parts if "/worksheets/" in name]
        return {
            "sheets": worksheets,
            "sheet_inventory": sheet_inventory,
            "formulas": len(formula_audit["cells"]),
            "formula_risks": formula_risks,
            "formula_audit": formula_audit,
            "formulas_calculated": False,
            "hidden": sum(item["visibility"] != "visible" for item in sheet_inventory),
            "hidden_rows": hidden_rows,
            "hidden_columns": hidden_columns,
            "charts": [name for name in parts if name.startswith("xl/charts/")],
            "active_content": active_content,
            "external_relationships": manifest["external_relationships"],
            "risks": risks,
        }
    def audit_formulas(self, path: Path) -> FormulaAudit:
        return cast(FormulaAudit, self.inspect(path)["formula_audit"])
    @staticmethod
    def recalculation_capability() -> dict[str, object]:
        return {
            "state": "unavailable", "recalculated": False,
            "reason": "no approved pinned spreadsheet calculation engine receipt is configured",
            "requires_approved_pinned_engine_receipt": True,
        }
    def recalculate(
        self, source: Path, output: Path | None = None, *,
        engine_receipt: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        _ = source, output, engine_receipt
        return self.recalculation_capability()
    def part_hashes(self, path: Path) -> dict[str, str]:
        return {name: item["original_sha256"] for name, item in preflight_package(path)["parts"].items()}
    def patch_cell(
        self,
        source: Path,
        output: Path,
        cell: str,
        value: object,
        *,
        expected_value: str | None = None,
        sheet_part: str = "xl/worksheets/sheet1.xml",
        expected_source_sha256: str | None = None,
    ) -> dict[str, object]:
        return patch_numeric_cell(
            source, output, cell, value, expected_value=expected_value,
            sheet_part=sheet_part, expected_source_sha256=expected_source_sha256,
        )
