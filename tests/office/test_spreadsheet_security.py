from __future__ import annotations

import hashlib
import socket
import zipfile
from pathlib import Path
from typing import cast

import pytest

from birkin.office.adapters.xlsx import XlsxAdapter
from birkin.office.csv_safety import (
    CsvCellRiskCode,
    inspect_delimited,
    safe_spreadsheet_export,
)
from birkin.office.errors import DocumentError, DocumentErrorCode


def _write_zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def _active_workbook(path: Path) -> Path:
    workbook = b"""<workbook xmlns:r="urn:rels"><sheets>
      <sheet name="Visible" sheetId="1" r:id="rId1"/>
      <sheet name="Hidden" sheetId="2" state="hidden" r:id="rId2"/>
      <sheet name="Deep" sheetId="3" state="veryHidden" r:id="rId3"/>
      <sheet name="Macro" sheetId="4" r:id="rId4"/>
    </sheets></workbook>"""
    relationships = b"""<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>
      <Relationship Id="rId2" Type="worksheet" Target="worksheets/sheet2.xml"/>
      <Relationship Id="rId3" Type="worksheet" Target="worksheets/sheet3.xml"/>
      <Relationship Id="rId4" Type="macrosheet" Target="macrosheets/sheet1.xml"/>
      <Relationship Id="rId5" Type="externalLink" Target="https://attacker.invalid/book.xlsx" TargetMode="External"/>
    </Relationships>"""
    sheet1 = b"""<worksheet><cols><col min="2" max="3" hidden="1"/><col min="6" max="6" hidden="true"/></cols><sheetData>
      <row r="2" hidden="1"><c r="A2"><f>cmd|' /C calc'!A0</f><v>0</v></c></row>
      <row r="3" hidden="true"/><row r="5" hidden="1"><c r="A5"><f>'[payroll.xlsx]Data'!A1</f><v>7</v></c></row>
    </sheetData></worksheet>"""
    return _write_zip(
        path,
        {
            "[Content_Types].xml": b"<Types/>",
            "xl/workbook.xml": workbook,
            "xl/_rels/workbook.xml.rels": relationships,
            "xl/worksheets/sheet1.xml": sheet1,
            "xl/worksheets/sheet2.xml": b"<worksheet><sheetData/></worksheet>",
            "xl/worksheets/sheet3.xml": b"<worksheet><sheetData/></worksheet>",
            "xl/macrosheets/sheet1.xml": b"<worksheet><sheetData/></worksheet>",
            "xl/vbaProject.bin": b"VBA-SENTINEL-NOT-EXECUTED",
            "xl/activeX/activeX1.bin": b"ACTIVEX-SENTINEL-NOT-EXECUTED",
            "xl/embeddings/oleObject1.bin": b"OLE-SENTINEL-NOT-EXECUTED",
        },
    )


def test_inspect_inventories_active_content_formulas_and_hidden_ranges_without_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _active_workbook(tmp_path / "active.xlsm")
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    def no_network(*_args: object, **_kwargs: object) -> socket.socket:
        raise AssertionError("spreadsheet inspection attempted network access")

    monkeypatch.setattr(socket, "socket", no_network)
    result = XlsxAdapter().inspect(source)
    active_content = cast(list[dict[str, object]], result["active_content"])
    formula_risks = cast(list[dict[str, object]], result["formula_risks"])
    sheet_inventory = cast(list[dict[str, object]], result["sheet_inventory"])

    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert {item["kind"] for item in active_content} == {
        "macro",
        "active_x",
        "embedded_object",
        "xlm_macro",
    }
    assert {item["code"] for item in formula_risks} == {
        "XLSX_DDE_FORMULA",
        "XLSX_EXTERNAL_WORKBOOK_FORMULA",
    }
    assert result["external_relationships"] == [
        {
            "part_uri": "xl/_rels/workbook.xml.rels",
            "relationship_id": "rId5",
            "target": "https://attacker.invalid/book.xlsx",
        }
    ]
    assert [(item["name"], item["visibility"]) for item in sheet_inventory] == [
        ("Visible", "visible"),
        ("Hidden", "hidden"),
        ("Deep", "veryHidden"),
        ("Macro", "visible"),
    ]
    assert result["hidden_rows"] == [
        {"sheet_part": "xl/worksheets/sheet1.xml", "ranges": ["2:3", "5"]}
    ]
    assert result["hidden_columns"] == [
        {"sheet_part": "xl/worksheets/sheet1.xml", "ranges": ["2:3", "6"]}
    ]
    assert result["formulas_calculated"] is False


def test_inspect_rejects_unbound_namespace_instead_of_normalizing(tmp_path: Path) -> None:
    source = _write_zip(
        tmp_path / "malformed.xlsx",
        {
            "[Content_Types].xml": b"<Types/>",
            "xl/workbook.xml": b'<workbook><sheets><x:sheet name="bad"/></sheets></workbook>',
        },
    )
    with pytest.raises(DocumentError) as caught:
        _ = XlsxAdapter().inspect(source)
    assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID
    assert caught.value.stage == "import"


@pytest.mark.parametrize(
    "cell",
    [
        "=1+1",
        "+SUM(A1:A2)",
        "-2+3",
        "@SUM(A1:A2)",
        "  =cmd|' /C calc'!A0",
        "\t=HYPERLINK(\"https://attacker.invalid\")",
        "\x00+1",
        "\u200b@SUM(A1:A2)",
        "\ufeff=1+1",
        "\uff1d1+1",
    ],
)
def test_csv_classifier_is_fail_closed_for_prefix_bypasses(cell: str) -> None:
    risk = inspect_delimited((f'"{cell.replace(chr(34), chr(34) * 2)}"\r\n').encode())
    assert len(risk) == 1
    assert risk[0].code is CsvCellRiskCode.FORMULA_INJECTION
    assert risk[0].cell == cell


def test_real_csv_and_tsv_are_scanned_after_parsing_and_quoting_is_not_a_defense(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "attack.csv"
    tsv_path = tmp_path / "attack.tsv"
    _ = csv_path.write_bytes(b'name,payload\r\nAda,"=WEBSERVICE(""https://attacker.invalid"")"\r\n')
    _ = tsv_path.write_bytes("name\tpayload\r\nAda\t\u200b+1\r\n".encode())

    csv_risks = inspect_delimited(csv_path.read_bytes())
    tsv_risks = inspect_delimited(tsv_path.read_bytes(), delimiter="\t")
    assert [(risk.row, risk.column) for risk in csv_risks] == [(2, 2)]
    assert [(risk.row, risk.column) for risk in tsv_risks] == [(2, 2)]


def test_safe_export_rejects_by_default_and_opt_in_returns_exact_change_evidence() -> None:
    rows = [["name", "payload"], ["Ada", "=1+1"], ["Lin", "safe"]]
    with pytest.raises(DocumentError) as caught:
        _ = safe_spreadsheet_export(rows)
    assert caught.value.code is DocumentErrorCode.POLICY_DENIED
    assert caught.value.details["risk_codes"] == ["CSV_FORMULA_INJECTION"]

    result = safe_spreadsheet_export(rows, neutralize=True)
    assert result.data == b"name,payload\r\nAda,'=1+1\r\nLin,safe\r\n"
    assert len(result.changed_cells) == 1
    change = result.changed_cells[0]
    assert (change.row, change.column, change.original, change.replacement) == (
        2,
        2,
        "=1+1",
        "'=1+1",
    )
    assert inspect_delimited(result.data) == ()
