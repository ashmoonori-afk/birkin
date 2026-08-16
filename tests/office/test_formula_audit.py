from __future__ import annotations

import hashlib
import socket
import zipfile
from pathlib import Path
from typing import cast

import pytest

from birkin.office.adapters.xlsx import XlsxAdapter


def _xlsx(path: Path) -> Path:
    workbook = b'''<workbook xmlns:r="urn:r"><fileVersion appName="xl" lastEdited="7" lowestEdited="6" rupBuild="12345"/><sheets><sheet name="Calc" sheetId="1" r:id="rId1"/></sheets><calcPr calcId="191029" calcMode="manual" fullCalcOnLoad="1" forceFullCalc="1" calcOnSave="0"/></workbook>'''
    sheet = b'''<worksheet><sheetData><row r="1">
<c r="A1"><f>1+1</f><v>999</v></c>
<c r="B1" t="e"><f>BADREF()</f><v>#REF!</v></c>
<c r="C1" t="e"><f>1/0</f><v>#DIV/0!</v></c>
<c r="D1" t="e"><f>VALUE_ERROR()</f><v>#VALUE!</v></c>
<c r="E1" t="e"><f>SPILL_ERROR()</f><v>#SPILL!</v></c>
<c r="F1"><f>40+2</f></c>
<c r="G1"><f t="shared" si="4" ref="G1:G2">A1*2</f><v>4</v></c>
<c r="H1"><f t="array" ref="H1:H3">_xlfn._xlws.FILTER(A1:A3,A1:A3&gt;0)</f><v>2</v></c>
<c r="I1"><f>'[source.xlsx]Data'!A1</f><v>9</v></c>
<c r="J1"><f>J1+1</f><v>1</v></c>
</row><row r="2"><c r="G2"><f t="shared" si="4"/><v>6</v></c></row></sheetData></worksheet>'''
    entries = {
        "[Content_Types].xml": b"<Types/>",
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": b'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="externalLink" Target="externalLinks/externalLink1.xml"/><Relationship Id="rId3" Type="connection" Target="https://attacker.invalid/feed" TargetMode="External"/></Relationships>''',
        "xl/worksheets/sheet1.xml": sheet,
        "xl/calcChain.xml": b'''<calcChain><c r="A1" i="1"/><c r="B1"/><c r="J1"/></calcChain>''',
        "xl/externalLinks/externalLink1.xml": b'''<externalLink><externalBook r:id="rId1" xmlns:r="urn:r"/></externalLink>''',
        "xl/externalLinks/_rels/externalLink1.xml.rels": b'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="externalLinkPath" Target="file:///private/source.xlsx" TargetMode="External"/></Relationships>''',
        "xl/connections.xml": b'''<connections><connection id="1" name="Feed" type="5" refreshOnLoad="1"/></connections>''',
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return path


def test_real_xlsx_formula_audit_keeps_formula_cache_error_and_chain_distinct(
    tmp_path: Path,
) -> None:
    audit = XlsxAdapter().audit_formulas(_xlsx(tmp_path / "audit.xlsx"))
    cells = {item["cell"]: item for item in cast(list[dict[str, object]], audit["cells"])}

    assert cells["A1"] == {
        "sheet": "Calc", "sheet_part": "xl/worksheets/sheet1.xml", "cell": "A1",
        "formula_text": "1+1", "formula_type": "normal", "shared_index": None,
        "formula_range": None, "cache_present": True, "cache_type": "number",
        "cache_value": "999", "cache_error": None, "cache_status": "stored_unverified",
        "in_calculation_chain": True,
    }
    assert cells["F1"]["cache_status"] == "missing"
    assert cells["F1"]["cache_present"] is False
    assert cells["B1"]["cache_error"] == "#REF!"
    assert cells["C1"]["cache_error"] == "#DIV/0!"
    assert cells["D1"]["cache_error"] == "#VALUE!"
    assert cells["E1"]["cache_error"] == "#SPILL!"
    assert cells["G1"]["formula_type"] == "shared"
    assert cells["G2"]["formula_text"] == ""
    assert cells["H1"]["formula_type"] == "array"
    assert cells["J1"]["in_calculation_chain"] is True
    assert audit["mathematical_correctness"] == "not_verified"
    assert audit["cache_freshness"] == "not_verified"


def test_real_xlsx_audits_calculation_version_dynamic_and_external_state_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _xlsx(tmp_path / "audit.xlsx")
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    def no_network(*_args: object, **_kwargs: object) -> socket.socket:
        raise AssertionError("formula audit attempted network access")

    monkeypatch.setattr(socket, "socket", no_network)
    inspected = XlsxAdapter().inspect(source)
    audit = cast(dict[str, object], inspected["formula_audit"])

    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert audit["calculation_properties"] == {
        "mode": "manual", "calculation_id": "191029", "full_calculation_on_load": True,
        "force_full_calculation": True, "calculate_on_save": False,
    }
    assert audit["workbook_version"] == {
        "application": "xl", "last_edited": "7", "lowest_edited": "6", "build": "12345",
    }
    chain = cast(dict[str, object], audit["calculation_chain"])
    assert chain["present"] is True and chain["entries"] == [
        {"sheet": "Calc", "sheet_index": 1, "cell": "A1"},
        {"sheet": "Calc", "sheet_index": 1, "cell": "B1"},
        {"sheet": "Calc", "sheet_index": 1, "cell": "J1"},
    ]
    dynamic = cast(list[dict[str, object]], audit["dynamic_arrays"])
    expected_future = [{
        "sheet": "Calc", "sheet_part": "xl/worksheets/sheet1.xml", "cell": "H1",
        "formula_text": "_xlfn._xlws.FILTER(A1:A3,A1:A3>0)", "formula_range": "H1:H3",
        "reason": "future_function_or_dynamic_array",
    }]
    assert dynamic == expected_future and audit["future_functions"] == expected_future
    assert audit["direct_self_references"] == [{
        "sheet": "Calc", "sheet_part": "xl/worksheets/sheet1.xml", "cell": "J1",
        "detection": "direct_self_reference",
    }]
    external = cast(dict[str, object], audit["external_links"])
    assert external["refresh_performed"] is False
    assert external["network_accessed"] is False
    assert external["formula_cells"] == [{
        "sheet": "Calc", "sheet_part": "xl/worksheets/sheet1.xml", "cell": "I1",
        "formula_text": "'[source.xlsx]Data'!A1",
    }]
    assert external["package_parts"] == ["xl/connections.xml", "xl/externalLinks/externalLink1.xml"]
    assert len(cast(list[object], external["relationships"])) == 2
    assert inspected["formulas"] == 11


def test_recalculation_is_explicitly_unavailable_and_creates_no_artifact(
    tmp_path: Path,
) -> None:
    source, output = _xlsx(tmp_path / "audit.xlsx"), tmp_path / "recalculated.xlsx"
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    adapter = XlsxAdapter()

    capability = adapter.recalculation_capability()
    result = adapter.recalculate(source, output)

    assert capability == {
        "state": "unavailable", "recalculated": False,
        "reason": "no approved pinned spreadsheet calculation engine receipt is configured",
        "requires_approved_pinned_engine_receipt": True,
    }
    assert result == capability
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert not output.exists()
