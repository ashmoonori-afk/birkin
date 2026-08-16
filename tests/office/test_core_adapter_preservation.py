from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from birkin.office.adapters.docx import DocxAdapter
from birkin.office.adapters.hwpx import HwpxAdapter
from birkin.office.adapters.pptx import PptxAdapter
from birkin.office.adapters.xlsx import XlsxAdapter
from birkin.office.errors import DocumentError, DocumentErrorCode

RELS = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdOpaque" Type="urn:custom" Target="opaque.bin"/></Relationships>'


def _package(path: Path, parts: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in parts.items():
            info = zipfile.ZipInfo(name, (2024, 1, 2, 3, 4, 6))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return path


def _hashes(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}


def _assert_only_changed(source: Path, output: Path, changed: str) -> None:
    before, after = _hashes(source), _hashes(output)
    assert before.keys() == after.keys()
    assert before[changed] != after[changed]
    assert {name: digest for name, digest in before.items() if name != changed} == {
        name: digest for name, digest in after.items() if name != changed
    }


def _docx(path: Path, *, duplicate: bool = False) -> Path:
    control = b'<w:sdt><w:sdtPr><w:tag w:val="customer"/></w:sdtPr><w:sdtContent><w:p w14:paraId="A1"><w:r><w:rPr><w:b/></w:rPr><w:t>PLACE</w:t></w:r><w:commentRangeStart w:id="2"/><w:fldSimple w:instr="DATE"><w:r><w:t>HOLDER</w:t></w:r></w:fldSimple></w:p></w:sdtContent></w:sdt>'
    body = control + (control if duplicate else b"")
    return _package(path, {
        "[Content_Types].xml": b"<Types/>", "_rels/.rels": RELS,
        "word/document.xml": b'<w:document xmlns:w="w" xmlns:w14="w14"><w:body>' + body + b"</w:body></w:document>",
        "word/styles.xml": b"<w:styles xmlns:w=\"w\"><w:style w:styleId=\"Sentinel\"/></w:styles>",
        "word/comments.xml": b"<w:comments xmlns:w=\"w\"><w:comment w:id=\"2\">sentinel</w:comment></w:comments>",
        "word/_rels/document.xml.rels": RELS, "custom/opaque.bin": b"DOCX-OPAQUE",
    })


def _xlsx(path: Path, *, duplicate: bool = False) -> Path:
    extra = b'<c r="A1"><v>7</v></c>' if duplicate else b""
    sheet = b'<worksheet xmlns="s"><sheetData><row r="1"><c r="A1" s="3"><v>7</v></c>' + extra + b'<c r="B1" s="4"><f>A1*2</f><v>14</v></c></row></sheetData><drawing r:id="rIdDraw" xmlns:r="r"/></worksheet>'
    return _package(path, {
        "[Content_Types].xml": b"<Types/>", "_rels/.rels": RELS,
        "xl/workbook.xml": b'<workbook xmlns:r="r"><sheets><sheet name="Data" sheetId="1" r:id="r1"/><sheet name="Hidden" sheetId="2" state="veryHidden" r:id="r2"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": RELS, "xl/worksheets/sheet1.xml": sheet,
        "xl/worksheets/_rels/sheet1.xml.rels": RELS, "xl/styles.xml": b"<styleSheet>SENTINEL</styleSheet>",
        "xl/charts/chart1.xml": b"<chart>SENTINEL</chart>", "xl/drawings/drawing1.xml": b"<drawing>SENTINEL</drawing>",
        "xl/vbaProject.bin": b"DO-NOT-EXECUTE", "custom/opaque.bin": b"XLSX-OPAQUE",
    })


def _pptx(path: Path, *, duplicate: bool = False) -> Path:
    shape = b'<p:sp><p:nvSpPr><p:nvPr><p:ph type="title" idx="7"/></p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:rPr b="1"/><a:t>PLACE</a:t></a:r><a:r><a:t>HOLDER</a:t></a:r></a:p></p:txBody></p:sp>'
    slide = b'<p:sld xmlns:p="p" xmlns:a="a"><p:cSld><p:spTree>' + shape + (shape if duplicate else b"") + b"</p:spTree></p:cSld></p:sld>"
    return _package(path, {
        "[Content_Types].xml": b"<Types/>", "_rels/.rels": RELS, "ppt/presentation.xml": b"<p:presentation xmlns:p=\"p\"/>",
        "ppt/slides/slide1.xml": slide, "ppt/slides/_rels/slide1.xml.rels": RELS,
        "ppt/slideMasters/slideMaster1.xml": b"<master>SENTINEL</master>", "ppt/slideLayouts/slideLayout1.xml": b"<layout>SENTINEL</layout>",
        "ppt/theme/theme1.xml": b"<theme>SENTINEL</theme>", "ppt/notesSlides/notesSlide1.xml": b"<notes>SENTINEL</notes>",
        "ppt/media/logo.png": b"PNG-SENTINEL", "custom/opaque.bin": b"PPTX-OPAQUE",
    })


def _hwpx(path: Path, *, duplicate: bool = False) -> Path:
    field = b'<hp:field id="customer"><hp:p paraId="H1"><hp:run charPrIDRef="9"><hp:t>PLACE</hp:t></hp:run><hp:run><hp:t>HOLDER</hp:t></hp:run></hp:p></hp:field>'
    section = b'<hs:sec xmlns:hs="hs" xmlns:hp="hp">' + field + b'<hp:tbl id="table-sentinel"/></hs:sec>'
    parts = {
        "mimetype": b"application/hwp+zip", "META-INF/manifest.xml": b"<manifest>SENTINEL</manifest>",
        "Contents/content.hpf": b"<opf>SENTINEL</opf>", "Contents/header.xml": b"<head><styles>SENTINEL</styles></head>",
        "Contents/section0.xml": section, "Contents/opaque.xml": b"<unknown>SENTINEL</unknown>",
    }
    if duplicate:
        parts["Contents/section1.xml"] = b'<hs:sec xmlns:hs="hs" xmlns:hp="hp">' + field + b"</hs:sec>"
    return _package(path, parts)


@pytest.mark.parametrize("stale", [False, True])
def test_docx_fragmented_field_is_surgical_and_refuses_stale_or_duplicate(tmp_path: Path, stale: bool) -> None:
    source = _docx(tmp_path / "source.docx", duplicate=not stale)
    output = tmp_path / "output.docx"
    with pytest.raises(DocumentError) as caught:
        _ = DocxAdapter().patch_field(source, output, "customer", "Ada", expected_text="STALE" if stale else "PLACEHOLDER")
    assert caught.value.code is (DocumentErrorCode.PRECONDITION_FAILED if stale else DocumentErrorCode.AMBIGUOUS_LOCATOR)
    assert not output.exists()


def test_docx_refuses_changed_source_precondition(tmp_path: Path) -> None:
    source, output = _docx(tmp_path / "source.docx"), tmp_path / "output.docx"
    with pytest.raises(DocumentError) as caught:
        _ = DocxAdapter().patch_field(
            source,
            output,
            "customer",
            "Ada",
            expected_source_sha256="0" * 64,
        )
    assert caught.value.code is DocumentErrorCode.SOURCE_CHANGED and not output.exists()


def test_docx_preserves_styles_comments_fields_relationships_and_unknown_parts(tmp_path: Path) -> None:
    source, output = _docx(tmp_path / "source.docx"), tmp_path / "output.docx"
    evidence = DocxAdapter().patch_field(source, output, "customer", "Ada & Co", expected_text="PLACEHOLDER")
    _assert_only_changed(source, output, "word/document.xml")
    with zipfile.ZipFile(output) as archive:
        xml = archive.read("word/document.xml")
    assert b"Ada &amp; Co" in xml and b"PLACE" not in xml and b"HOLDER" not in xml
    assert b"<w:rPr><w:b/></w:rPr>" in xml and b"commentRangeStart" in xml and b"fldSimple" in xml
    assert evidence["source_part"] == "word/document.xml" and evidence["calculated"] is False


def test_xlsx_preserves_formula_cache_styles_hidden_drawing_chart_and_active_parts(tmp_path: Path) -> None:
    source, output = _xlsx(tmp_path / "source.xlsx"), tmp_path / "output.xlsx"
    evidence = XlsxAdapter().patch_cell(source, output, "A1", 9, expected_value="7")
    _assert_only_changed(source, output, "xl/worksheets/sheet1.xml")
    with zipfile.ZipFile(output) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml")
    assert b'<c r="A1" s="3"><v>9</v></c>' in sheet and b"<f>A1*2</f><v>14</v>" in sheet
    assert evidence == {"calculated": False, "cell": "A1", "source_part": "xl/worksheets/sheet1.xml"}


@pytest.mark.parametrize("cell, duplicate, code", [("B1", False, DocumentErrorCode.LOSSY_WRITE_BLOCKED), ("A1", True, DocumentErrorCode.AMBIGUOUS_LOCATOR)])
def test_xlsx_refuses_formula_cache_mutation_and_ambiguous_cells(tmp_path: Path, cell: str, duplicate: bool, code: DocumentErrorCode) -> None:
    source, output = _xlsx(tmp_path / "source.xlsx", duplicate=duplicate), tmp_path / "output.xlsx"
    with pytest.raises(DocumentError) as caught:
        _ = XlsxAdapter().patch_cell(source, output, cell, 8)
    assert caught.value.code is code and not output.exists()


def test_xlsx_refuses_string_write_that_would_change_cell_storage(tmp_path: Path) -> None:
    source, output = _xlsx(tmp_path / "source.xlsx"), tmp_path / "output.xlsx"
    with pytest.raises(DocumentError) as caught:
        _ = XlsxAdapter().patch_cell(source, output, "A1", "text")
    assert caught.value.code is DocumentErrorCode.UNSUPPORTED_EDIT and not output.exists()


def test_pptx_fragmented_placeholder_preserves_presentation_graph_and_media(tmp_path: Path) -> None:
    source, output = _pptx(tmp_path / "source.pptx"), tmp_path / "output.pptx"
    evidence = PptxAdapter().patch_placeholder(source, output, 7, "New title", expected_text="PLACEHOLDER")
    _assert_only_changed(source, output, "ppt/slides/slide1.xml")
    with zipfile.ZipFile(output) as archive:
        slide = archive.read("ppt/slides/slide1.xml")
    assert b"New title" in slide and b"PLACE" not in slide and b"HOLDER" not in slide and b'<a:rPr b="1"/>' in slide
    assert evidence["rendered"] is False and evidence["source_part"] == "ppt/slides/slide1.xml"


def test_pptx_refuses_duplicate_placeholder(tmp_path: Path) -> None:
    source, output = _pptx(tmp_path / "source.pptx", duplicate=True), tmp_path / "output.pptx"
    with pytest.raises(DocumentError) as caught:
        _ = PptxAdapter().patch_placeholder(source, output, 7, "New title")
    assert caught.value.code is DocumentErrorCode.AMBIGUOUS_LOCATOR and not output.exists()


def test_hwpx_preserves_manifest_styles_table_and_unknown_parts(tmp_path: Path) -> None:
    source, output = _hwpx(tmp_path / "source.hwpx"), tmp_path / "output.hwpx"
    evidence = HwpxAdapter().patch_field(source, output, "customer", "Ada", expected_text="PLACEHOLDER")
    _assert_only_changed(source, output, "Contents/section0.xml")
    with zipfile.ZipFile(output) as archive:
        section = archive.read("Contents/section0.xml")
    assert b">Ada</hp:t>" in section and b"PLACE" not in section and b"HOLDER" not in section and b"table-sentinel" in section
    assert evidence["source_part"] == "Contents/section0.xml"


@pytest.mark.parametrize("duplicate, expected, code", [(True, None, DocumentErrorCode.AMBIGUOUS_LOCATOR), (False, "STALE", DocumentErrorCode.PRECONDITION_FAILED)])
def test_hwpx_refuses_duplicate_ids_and_stale_text(tmp_path: Path, duplicate: bool, expected: str | None, code: DocumentErrorCode) -> None:
    source, output = _hwpx(tmp_path / "source.hwpx", duplicate=duplicate), tmp_path / "output.hwpx"
    with pytest.raises(DocumentError) as caught:
        _ = HwpxAdapter().patch_field(source, output, "customer", "Ada", expected_text=expected)
    assert caught.value.code is code and not output.exists()
