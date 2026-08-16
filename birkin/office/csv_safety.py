"""Fail-closed delimited-text byte contracts and spreadsheet cell safety."""

from __future__ import annotations

import csv
import hashlib
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from .csv_contract import (
    CsvDialect,
    CsvEncoding,
    CsvExportPlan,
    CsvImportPlan,
    CsvNewline,
    CsvQuotePolicy,
    CsvSniffPolicy,
    encode_delimited,
    newline_text,
    parse_delimited,
    quoting_value,
    receipt_hash,
)
from .csv_runtime import parse_standard_rows, render_csv_rows
from .errors import DocumentError, DocumentErrorCode

__all__ = ("CsvCellChange", "CsvCellRisk", "CsvCellRiskCode", "CsvDialect", "CsvEncoding", "CsvExportPlan", "CsvImportPlan", "CsvImportResult", "CsvNewline", "CsvQuotePolicy", "CsvSniffPolicy", "SafeSpreadsheetExport", "classify_csv_cell", "export_delimited", "import_delimited", "inspect_delimited", "safe_spreadsheet_export")


class CsvCellRiskCode(str, Enum):
    FORMULA_INJECTION = "CSV_FORMULA_INJECTION"


@dataclass(frozen=True, slots=True)
class CsvCellRisk:
    code: CsvCellRiskCode
    row: int
    column: int
    cell: str
    trigger: str


@dataclass(frozen=True, slots=True)
class CsvCellChange:
    row: int
    column: int
    risk_code: CsvCellRiskCode
    original: str
    replacement: str


@dataclass(frozen=True, slots=True)
class CsvImportResult:
    rows: tuple[tuple[str, ...], ...]
    risks: tuple[CsvCellRisk, ...]
    plan: CsvImportPlan
    source_sha256: str
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class SafeSpreadsheetExport:
    data: bytes
    changed_cells: tuple[CsvCellChange, ...]
    output_sha256: str
    receipt_sha256: str


CsvDelimitedImport = CsvImportResult
CsvDelimitedExport = SafeSpreadsheetExport
DelimitedImportPlan = CsvImportPlan
DelimitedExportPlan = CsvExportPlan
DelimitedDialect = CsvDialect
DelimitedEncoding = CsvEncoding
DelimitedNewline = CsvNewline


def _delimiter(value: str) -> str:
    try:
        _ = CsvDialect(delimiter=value)
    except ValueError as exc:
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "export",
            "CSV delimiter must be one non-quote, non-line-break character",
        ) from exc
    return value


def _dangerous_trigger(cell: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", cell)
    index = 0
    while index < len(normalized) and unicodedata.category(normalized[index])[0] in {"C", "Z"}:
        index += 1
    if index < len(normalized) and normalized[index] in "=+-@":
        return normalized[index]
    return None


def classify_csv_cell(cell: object, *, row: int = 1, column: int = 1) -> CsvCellRisk | None:
    """Classify an application-interpretable formula without evaluating it."""
    if not isinstance(cell, str) or row < 1 or column < 1:
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "inspect",
            "CSV cells must be strings with positive coordinates",
        )
    trigger = _dangerous_trigger(cell)
    if trigger is None:
        return None
    return CsvCellRisk(CsvCellRiskCode.FORMULA_INJECTION, row, column, cell, trigger)


def _risks(rows: Iterable[Sequence[str]]) -> tuple[CsvCellRisk, ...]:
    findings: list[CsvCellRisk] = []
    for row_number, row in enumerate(rows, 1):
        for column_number, cell in enumerate(row, 1):
            risk = classify_csv_cell(cell, row=row_number, column=column_number)
            if risk is not None:
                findings.append(risk)
    return tuple(findings)


def inspect_delimited(data: bytes, *, delimiter: str = ",") -> tuple[CsvCellRisk, ...]:
    """Compatibility scanner for strict UTF-8/UTF-8-BOM CSV and TSV bytes."""
    separator = _delimiter(delimiter)
    try:
        text = data.decode("utf-8-sig")
        rows = parse_standard_rows(text, separator)
        return _risks(rows)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "inspect",
            "delimited input is not valid strict UTF-8 CSV/TSV",
        ) from exc


def _dialect_record(dialect: CsvDialect) -> dict[str, object]:
    return {
        "delimiter": dialect.delimiter,
        "quotechar": dialect.quotechar,
        "escapechar": dialect.escapechar,
        "doublequote": dialect.doublequote,
        "quote_policy": dialect.quote_policy.value,
    }


def import_delimited(data: bytes, plan: CsvImportPlan) -> CsvImportResult:
    """Decode and parse bytes under an explicit, strict import plan."""
    parsed = parse_delimited(data, plan)
    risks = _risks(parsed.rows)
    receipt: dict[str, object] = {
        "operation": "delimited_import",
        "version": 1,
        "source_sha256": parsed.source_sha256,
        "encoding": parsed.plan.encoding.value,
        "dialect": _dialect_record(parsed.plan.dialect),
        "newline": parsed.plan.newline.value,
        "strict_decode": True,
        "rows": len(parsed.rows),
    }
    return CsvImportResult(
        parsed.rows, risks, parsed.plan, parsed.source_sha256, receipt_hash(receipt)
    )


def _materialize(rows: Iterable[Sequence[object]]) -> list[list[str]]:
    result: list[list[str]] = []
    for row in rows:
        if isinstance(row, (str, bytes)):
            raise DocumentError(DocumentErrorCode.INVALID_INPUT, "export", "CSV rows must be sequences of strings")
        output: list[str] = []
        for cell in row:
            if not isinstance(cell, str):
                raise DocumentError(DocumentErrorCode.INVALID_INPUT, "export", "CSV cells must be strings")
            output.append(cell)
        result.append(output)
    return result


def _deny(risks: tuple[CsvCellRisk, ...]) -> None:
    raise DocumentError(
        DocumentErrorCode.POLICY_DENIED,
        "export",
        "spreadsheet-target export contains formula-injection cells",
        details={
            "risk_codes": sorted({risk.code.value for risk in risks}),
            "cells": [{"row": risk.row, "column": risk.column} for risk in risks],
        },
    )


def export_delimited(
    rows: Iterable[Sequence[object]], plan: CsvExportPlan
) -> SafeSpreadsheetExport:
    """Produce deterministic bytes under an explicit spreadsheet safety plan."""
    materialized = _materialize(rows)
    risks = _risks(materialized) if plan.spreadsheet_target else ()
    if risks and not plan.neutralize:
        _deny(risks)
    if any(char not in "\t\r\n" and unicodedata.category(char) == "Cc" for row in materialized for cell in row for char in cell):
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "export", "CSV cells contain a forbidden control character")
    changes: list[CsvCellChange] = []
    for risk in risks:
        replacement = "'" + risk.cell
        materialized[risk.row - 1][risk.column - 1] = replacement
        changes.append(CsvCellChange(risk.row, risk.column, risk.code, risk.cell, replacement))
    dialect = plan.dialect
    try:
        text = render_csv_rows(
            materialized,
            delimiter=dialect.delimiter,
            quotechar=dialect.quotechar,
            escapechar=dialect.escapechar,
            doublequote=dialect.doublequote,
            quoting=quoting_value(dialect.quote_policy),
            lineterminator=newline_text(plan.newline),
        )
    except csv.Error as exc:
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "export", "cells violate the export dialect plan") from exc
    data = encode_delimited(text, plan.encoding)
    output_sha256 = hashlib.sha256(data).hexdigest()
    receipt: dict[str, object] = {
        "operation": "delimited_export",
        "version": 1,
        "output_sha256": output_sha256,
        "encoding": plan.encoding.value,
        "dialect": _dialect_record(dialect),
        "newline": plan.newline.value,
        "spreadsheet_target": plan.spreadsheet_target,
        "neutralized_cells": len(changes),
        "rows": len(materialized),
    }
    return SafeSpreadsheetExport(data, tuple(changes), output_sha256, receipt_hash(receipt))


def safe_spreadsheet_export(
    rows: Iterable[Sequence[object]], *, delimiter: str = ",", neutralize: bool = False
) -> SafeSpreadsheetExport:
    """Compatibility export: UTF-8/CRLF, default-deny spreadsheet formulas."""
    separator = _delimiter(delimiter)
    return export_delimited(
        rows,
        CsvExportPlan(dialect=CsvDialect(delimiter=separator), neutralize=neutralize),
    )
