"""Bounded, evidence-linked XLSX review and aggregation."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import cast

from .create_backends import module_member, optional_backend
from .errors import DocumentError, DocumentErrorCode

_MAX_CELLS = 10_000


def _invalid(message: str) -> DocumentError:
    return DocumentError(DocumentErrorCode.INVALID_INPUT, "analyze", message)


def _kind(value: object) -> str:
    if value is None:
        return "blank"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (datetime, date)):
        return "date"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, str) and value.startswith("="):
        return "formula"
    # openpyxl loads array and data-table formulas as objects, not "=" strings.
    if type(value).__name__ in {"ArrayFormula", "DataTableFormula"}:
        return "formula"
    return "text"


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _display(value: object) -> str:
    return value.isoformat() if isinstance(value, (date, datetime)) else "" if value is None else str(value)


def _period_sort_key(value: object, key: str) -> tuple[int, object]:
    # Dates and numbers sort natively; text sorts digit runs as integers (1월..12월, 2024-Q4 < 2025-Q1).
    if value is None or (isinstance(value, str) and not value.strip()):
        return (-1, "")  # a blank period is never "previous" or "current"
    if isinstance(value, (date, datetime)):
        return (0, key)
    if (number := _number(value)) is not None:
        return (1, number)
    # Digit runs compare by length then text (no int(): a cell may hold a
    # digit run past Python's int-parsing limit).
    parts = re.split(r"([0-9]+)", key)
    return (2, tuple((0, len(digits := part.lstrip("0") or "0"), digits) if index % 2 else (1, 0, part.casefold()) for index, part in enumerate(parts)))


def analyze_xlsx(
    path: Path,
    source_sha256: str,
    *,
    sheet: object,
    cell_range: object,
    group_by: object = None,
    value_column: object = None,
    compare_by: object = None,
    include_hidden_rows: object = False,
) -> dict[str, object]:
    if not isinstance(sheet, str) or not sheet or not isinstance(cell_range, str) or not cell_range:
        raise _invalid("sheet and cell_range must be non-empty strings")
    if not isinstance(include_hidden_rows, bool):
        raise _invalid("include_hidden_rows must be a boolean")
    if any(value is not None and (not isinstance(value, str) or not value) for value in (group_by, value_column, compare_by)):
        raise _invalid("group_by, value_column, and compare_by must be non-empty strings")
    load_workbook = cast("Callable[..., object]", module_member(optional_backend("openpyxl", "xlsx"), "load_workbook"))
    range_boundaries = cast("Callable[[str], tuple[int, int, int, int]]", module_member(optional_backend("openpyxl.utils.cell", "xlsx"), "range_boundaries"))
    try:
        min_col, min_row, max_col, max_row = range_boundaries(cell_range)
    except ValueError as exc:
        raise _invalid("cell_range must be a valid XLSX range") from exc
    if (max_col - min_col + 1) * (max_row - min_row + 1) > _MAX_CELLS:
        raise _invalid(f"selected range exceeds the {_MAX_CELLS} cell limit")
    with path.open("rb") as source:
        workbook = load_workbook(source, read_only=False, data_only=False, keep_links=False)
    with path.open("rb") as source:
        cached_workbook = load_workbook(source, read_only=False, data_only=True, keep_links=False)
    try:
        if sheet not in workbook.sheetnames:
            raise _invalid("worksheet was not found")
        worksheet = workbook[sheet]
        cached_sheet = cached_workbook[sheet]
        headers = [_display(worksheet.cell(min_row, column).value) for column in range(min_col, max_col + 1)]
        if any(not header for header in headers) or len(set(headers)) != len(headers):
            raise _invalid("selected range requires unique non-empty headers in its first row")
        indexes = {header: index for index, header in enumerate(headers)}
        for label, value in (("group_by", group_by), ("value_column", value_column), ("compare_by", compare_by)):
            if value is not None and value not in indexes:
                raise _invalid(f"{label} must name a selected header")
        if (group_by is not None or compare_by is not None) and value_column is None:
            raise _invalid("value_column is required for grouping or comparison")
        rows: list[tuple[int, list[object]]] = []
        hidden_excluded: list[int] = []
        kinds: Counter[str] = Counter()
        formats: Counter[str] = Counter()
        formula_cache = Counter()
        for row_number in range(min_row + 1, max_row + 1):
            hidden = worksheet.row_dimensions[row_number].hidden is True
            if hidden and not include_hidden_rows:
                hidden_excluded.append(row_number)
                continue
            values: list[object] = []
            for column in range(min_col, max_col + 1):
                cell = worksheet.cell(row_number, column)
                value = cell.value
                values.append(value)
                kind = _kind(value)
                kinds[kind] += 1
                if isinstance(cell.number_format, str) and "%" in cell.number_format:
                    formats["percentage"] += 1
                elif isinstance(cell.number_format, str) and any(token in cell.number_format for token in ("$", "₩", "€", "£")):
                    formats["currency"] += 1
                if kind == "formula":
                    formula_cache["present_unverified" if cached_sheet.cell(row_number, column).value is not None else "missing"] += 1
            rows.append((row_number, values))
        seen: dict[tuple[str, ...], int] = {}
        duplicates: list[dict[str, object]] = []
        for row_number, values in rows:
            key = tuple(_display(value) for value in values)
            if key in seen:
                duplicates.append({"row": row_number, "duplicate_of": seen[key]})
            else:
                seen[key] = row_number
        value_index = indexes.get(cast("str", value_column)) if value_column is not None else None
        valued: list[tuple[int, list[object], float]] = []
        cached_formula_cells: list[str] = []
        excluded_formula_cells: list[str] = []
        if value_index is not None:
            for row_number, values in rows:
                number = _number(values[value_index])
                if _kind(values[value_index]) == "formula":
                    coordinate = worksheet.cell(row_number, min_col + value_index).coordinate
                    number = _number(cached_sheet.cell(row_number, min_col + value_index).value)
                    (cached_formula_cells if number is not None else excluded_formula_cells).append(coordinate)
                if number is not None:
                    valued.append((row_number, values, number))
        numeric = [(row_number, number) for row_number, _, number in valued]
        grouped: defaultdict[str, float] = defaultdict(float)
        grouped_cells: defaultdict[str, list[str]] = defaultdict(list)
        if group_by is not None and value_index is not None:
            group_index = indexes[cast("str", group_by)]
            for row_number, values, number in valued:
                key = _display(values[group_index])
                grouped[key] += number
                grouped_cells[key].append(worksheet.cell(row_number, min_col + value_index).coordinate)
        periods: defaultdict[str, float] = defaultdict(float)
        period_keys: dict[str, tuple[int, object]] = {}
        if compare_by is not None and value_index is not None:
            period_index = indexes[cast("str", compare_by)]
            for _, values, number in valued:
                key = _display(values[period_index])
                periods[key] += number
                period_keys.setdefault(key, _period_sort_key(values[period_index], key))
        ordered_periods = [key for key in sorted(periods, key=period_keys.__getitem__) if period_keys[key][0] != -1]
        comparison = None
        if len(ordered_periods) >= 2:
            previous, current = ordered_periods[-2:]
            ranks = {period_keys[key][0] for key in ordered_periods}
            ordering = {0: "chronological", 1: "numeric", 2: "natural_text"}[ranks.pop()] if len(ranks) == 1 else "mixed_type"
            comparison = {"previous": previous, "current": current, "previous_total": periods[previous], "current_total": periods[current], "delta": periods[current] - periods[previous], "ordering": ordering}
        total = sum(number for _, number in numeric)
        if value_index is None:
            total_paragraphs = ["합계: 미요청"]
        else:
            total_paragraphs = [f"부분 합계: {total}" if excluded_formula_cells else f"합계: {total}"]
            if cached_formula_cells:
                total_paragraphs.append(f"수식 {len(cached_formula_cells)}개는 저장된 계산값을 재계산 없이 사용함")
            if excluded_formula_cells:
                total_paragraphs.append(f"수식 {len(excluded_formula_cells)}개는 숫자 계산값이 저장되어 있지 않아 합계에서 제외됨")
        return {
            "status": "needs_review" if excluded_formula_cells else "reviewed",
            "source_sha256": source_sha256,
            "selection": {"sheet": sheet, "range": cell_range, "included_rows": len(rows), "hidden_rows_excluded": hidden_excluded},
            "profile": {"types": dict(kinds), "formats": dict(formats), "blank_cells": kinds["blank"], "duplicates": duplicates},
            "aggregate": {
                "value_column": value_column,
                "sum": total if value_index is not None else None,
                "evidence": [worksheet.cell(row, min_col + cast(int, value_index)).coordinate for row, _ in numeric] if value_index is not None else [],
                "cached_formula_evidence": cached_formula_cells,
                "excluded_formula_cells": excluded_formula_cells,
                "groups": [{"key": key, "sum": grouped[key], "evidence": grouped_cells[key]} for key in sorted(grouped)],
                "comparison": comparison,
            },
            "calculation": {"performed": False, "formula_cache": dict(formula_cache), "status": "not_recalculated"},
            "policies": {
                "dates": "openpyxl date values retain ISO date or datetime semantics",
                "currency": "numeric value; number format reported separately",
                "percentage": "stored numeric fraction; number format reported separately",
                "numeric_strings": "kept as text and excluded from sums",
                "formulas": "value_column formulas use the stored numeric cached value without recalculation; formulas without one are excluded and listed",
                "hidden_rows": "included only when include_hidden_rows is true",
            },
            "report_content": {
                "title": f"{sheet} 데이터 검토",
                "paragraphs": [f"범위: {cell_range}", *total_paragraphs],
                "table": [["그룹", "합계"], *[[key, str(grouped[key])] for key in sorted(grouped)]],
                "list": [f"빈 셀: {kinds['blank']}", f"중복 행: {len(duplicates)}", "수식 재계산: 미실행"],
            },
        }
    finally:
        workbook.close()
        cached_workbook.close()


__all__ = ["analyze_xlsx"]
