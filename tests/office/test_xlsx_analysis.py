from __future__ import annotations

import hashlib
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import cast

import pytest
from docx import Document
from openpyxl import Workbook

from birkin.office.service import DocumentService


def _artifact(path: Path) -> dict[str, str]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"uri": str(path), "content_hash": digest}


def _workbook(path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["Period", "Category", "Amount", "Rate", "TextNumber", "Formula"])
    rows = [
        [date(2026, 1, 1), "A", 100, 0.10, "200", "=C2*2"],
        [date(2026, 1, 1), "A", 50, 0.20, "300", "=C3*2"],
        [date(2026, 2, 1), "A", 130, 0.15, "400", "=C4*2"],
        [date(2026, 2, 1), "B", 40, 0.05, "500", "=C5*2"],
        [date(2026, 2, 1), "B", 40, 0.05, "500", "=C5*2"],
        [date(2026, 2, 1), "Hidden", 999, 0.99, "999", "=C7*2"],
    ]
    for row in rows:
        sheet.append(row)
    for row in range(2, 8):
        sheet.cell(row, 3).number_format = "$#,##0.00"
        sheet.cell(row, 4).number_format = "0%"
    sheet.row_dimensions[7].hidden = True
    workbook.save(path)
    return path


def test_xlsx_review_aggregates_with_cell_evidence_and_explicit_policies(tmp_path: Path) -> None:
    service = DocumentService(tmp_path)
    source = _workbook(tmp_path / "sales.xlsx")

    result = service.analyze_workbook(
        _artifact(source),
        sheet="Sales",
        cell_range="A1:F7",
        group_by="Category",
        value_column="Amount",
        compare_by="Period",
    )

    assert result["source_sha256"] == _artifact(source)["content_hash"]
    assert result["selection"]["hidden_rows_excluded"] == [7]
    assert result["profile"]["duplicates"] == [{"row": 6, "duplicate_of": 5}]
    aggregate = result["aggregate"]
    assert aggregate["sum"] == 360
    assert aggregate["evidence"] == ["C2", "C3", "C4", "C5", "C6"]
    assert aggregate["groups"] == [
        {"key": "A", "sum": 280, "evidence": ["C2", "C3", "C4"]},
        {"key": "B", "sum": 80, "evidence": ["C5", "C6"]},
    ]
    assert aggregate["comparison"]["delta"] == 60
    assert result["calculation"] == {
        "performed": False,
        "formula_cache": {"missing": 5},
        "status": "not_recalculated",
    }
    assert result["policies"]["numeric_strings"].startswith("kept as text")

    created = service.create_document(
        format="docx",
        content=cast("dict[str, object]", result["report_content"]),
        output_name="sales-review.docx",
    )
    assert Document(created["draft_artifact"]["uri"]).paragraphs[0].text == "Sales 데이터 검토"


def _inject_formula_cache(path: Path, cached: dict[str, float]) -> Path:
    # openpyxl writes formula cells as <c r="D2"><f>..</f><v></v></c>; fill <v> like Excel would on save.
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    sheet_xml = entries["xl/worksheets/sheet1.xml"].decode()
    for coordinate, value in cached.items():
        sheet_xml, count = re.subn(rf'(<c r="{coordinate}"[^>]*><f[^>]*>[^<]*</f>)<v\s*(?:/>|></v>)', rf"\g<1><v>{value}</v>", sheet_xml)
        assert count == 1
    entries["xl/worksheets/sheet1.xml"] = sheet_xml.encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return path


def _formula_workbook(path: Path, *, cache_rows: range) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["월", "단가", "수량", "금액"])
    for month in range(1, 13):
        sheet.append([f"{month}월", 10, month, f"=B{month + 1}*C{month + 1}"])
    workbook.save(path)
    return _inject_formula_cache(path, {f"D{row}": 10 * (row - 1) for row in cache_rows})


def test_xlsx_review_sums_cached_formula_values_with_marked_evidence(tmp_path: Path) -> None:
    service = DocumentService(tmp_path)
    source = _formula_workbook(tmp_path / "formulas.xlsx", cache_rows=range(2, 14))

    result = service.analyze_workbook(
        _artifact(source), sheet="Sales", cell_range="A1:D13", group_by="월", value_column="금액", compare_by="월"
    )

    assert result["status"] == "reviewed"
    aggregate = result["aggregate"]
    assert aggregate["sum"] == 780
    assert aggregate["evidence"] == [f"D{row}" for row in range(2, 14)]
    assert aggregate["cached_formula_evidence"] == [f"D{row}" for row in range(2, 14)]
    assert aggregate["excluded_formula_cells"] == []
    assert len(aggregate["groups"]) == 12
    assert result["calculation"]["performed"] is False
    assert result["calculation"]["formula_cache"] == {"present_unverified": 12}
    assert "formulas" in result["policies"]
    assert "합계: 780.0" in result["report_content"]["paragraphs"]
    comparison = aggregate["comparison"]
    assert (comparison["previous"], comparison["current"]) == ("11월", "12월")
    assert comparison["delta"] == 10


def test_xlsx_review_excludes_formulas_without_cache_and_flags_partial_sum(tmp_path: Path) -> None:
    service = DocumentService(tmp_path)
    source = _formula_workbook(tmp_path / "partial.xlsx", cache_rows=range(2, 12))

    result = service.analyze_workbook(_artifact(source), sheet="Sales", cell_range="A1:D13", value_column="금액")

    assert result["status"] == "needs_review"
    aggregate = result["aggregate"]
    assert aggregate["sum"] == 550
    assert aggregate["excluded_formula_cells"] == ["D12", "D13"]
    paragraphs = result["report_content"]["paragraphs"]
    assert "합계: 550.0" not in paragraphs
    assert "부분 합계: 550.0" in paragraphs
    assert "수식 2개는 숫자 계산값이 저장되어 있지 않아 합계에서 제외됨" in paragraphs


def test_xlsx_review_counts_array_formulas_like_other_formulas(tmp_path: Path) -> None:
    from openpyxl.worksheet.formula import ArrayFormula

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["월", "금액"])
    sheet.append(["1월", 5])
    sheet["B3"] = ArrayFormula("B3", "=SUM(B2:B2)*2")
    sheet["A3"] = "2월"
    sheet["A4"] = "3월"
    sheet["B4"] = ArrayFormula("B4", "=SUM(B2:B2)*3")
    source = tmp_path / "array.xlsx"
    workbook.save(source)
    _inject_formula_cache(source, {"B3": 10})

    result = DocumentService(tmp_path).analyze_workbook(
        _artifact(source), sheet="Sales", cell_range="A1:B4", value_column="금액"
    )

    aggregate = result["aggregate"]
    assert aggregate["sum"] == 15                     # 5 + cached 10
    assert aggregate["cached_formula_evidence"] == ["B3"]
    assert aggregate["excluded_formula_cells"] == ["B4"]   # never silently dropped
    assert result["status"] == "needs_review"


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        ([f"{month}월" for month in range(1, 13)], ("11월", "12월", "natural_text")),
        (list(range(1, 13)), ("11", "12", "numeric")),
        (["2026-8", "2026-9", "2026-10"], ("2026-9", "2026-10", "natural_text")),
        (["2024-Q3", "2024-Q4", "2025-Q1"], ("2024-Q4", "2025-Q1", "natural_text")),
        (["9" * 5000, "1" + "0" * 5000], ("9" * 5000, "1" + "0" * 5000, "natural_text")),
        ([2024, 2025, None], ("2024", "2025", "numeric")),
        ([date(2024, 1, 1), date(2025, 1, 1), None], ("2024-01-01T00:00:00", "2025-01-01T00:00:00", "chronological")),
    ],
)
def test_xlsx_period_comparison_uses_natural_ordering(
    tmp_path: Path, labels: list[object], expected: tuple[str, str, str]
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["Period", "Amount"])
    for index, label in enumerate(labels, start=1):
        sheet.append([label, index])
    source = tmp_path / "periods.xlsx"
    workbook.save(source)

    result = DocumentService(tmp_path).analyze_workbook(
        _artifact(source), sheet="Sales", cell_range=f"A1:B{len(labels) + 1}", value_column="Amount", compare_by="Period"
    )

    comparison = result["aggregate"]["comparison"]
    assert (comparison["previous"], comparison["current"], comparison["ordering"]) == expected
    assert comparison["delta"] == 1
