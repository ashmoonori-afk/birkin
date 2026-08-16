from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from birkin.office.adapters.hwpx import HwpxAdapter
from birkin.office.adapters.hwpx_types import (
    CellLocator,
    ParagraphLocator,
    TextLocator,
)
from birkin.office.errors import DocumentError, DocumentErrorCode

SECTION0 = b'''<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
 xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
 <hp:p id="p-ko"><hp:run charPrIDRef="7"><hp:t>\xed\x95\x9c\xea\xb8\x80 </hp:t><hp:t>English</hp:t></hp:run></hp:p>
 <hp:p id="p-field"><hp:run><hp:ctrl><hp:fieldBegin id="f-1" name="customer" type="CLICK_HERE"/></hp:ctrl><hp:t>\xea\xb3\xa0\xea\xb0\x9d\xeb\xaa\x85</hp:t><hp:ctrl><hp:fieldEnd beginIDRef="f-1"/></hp:ctrl></hp:run></hp:p>
 <hp:tbl id="orders" borderFillIDRef="4"><hp:tr><hp:tc id="cell-a1" styleIDRef="8"><hp:cellAddr colAddr="0" rowAddr="0"/><hp:cellSpan colSpan="2" rowSpan="1"/><hp:subList><hp:p id="cell-p"><hp:run charPrIDRef="9"><hp:t>\xec\x83\x81\xed\x92\x88 A</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl>
</hs:sec>'''
SECTION1 = b'''<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p id="p-en"><hp:run><hp:t>Second section</hp:t></hp:run></hp:p></hs:sec>'''


def _package(path: Path, *, section0: bytes = SECTION0, section1: bytes = SECTION1) -> Path:
    entries = [
        ("mimetype", b"application/hwp+zip"),
        ("META-INF/manifest.xml", b'<manifest xmlns="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"><file-entry full-path="Contents/section0.xml"/></manifest>'),
        ("Contents/content.hpf", b'<opf xmlns="http://www.idpf.org/2007/opf"><metadata><title>\xed\x85\x9c\xed\x94\x8c\xeb\xa6\xbf</title></metadata></opf>'),
        ("Contents/header.xml", b'<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"><hh:fontfaces><hh:fontface lang="HANGUL"><hh:font id="0" face="\xed\x95\xa8\xec\xb4\x88\xeb\xa1\xac"/></hh:fontface></hh:fontfaces><hh:styles><hh:style id="3" name="Body"/></hh:styles></hh:head>'),
        ("Contents/masterPage0.xml", b'<hm:masterPage xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" id="master-0"><hm:header>keep</hm:header><hm:footer>keep</hm:footer></hm:masterPage>'),
        ("Contents/section0.xml", section0),
        ("Contents/section1.xml", section1),
        ("BinData/opaque.bin", b"UNKNOWN-RELATIONSHIP-PAYLOAD"),
    ]
    with zipfile.ZipFile(path, "w") as archive:
        for index, (name, payload) in enumerate(entries):
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_STORED if index == 0 else zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return path


def _hashes(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}


def test_inventory_has_stable_locators_fields_cells_and_metadata(tmp_path: Path) -> None:
    source = _package(tmp_path / "rich.hwpx")
    info = HwpxAdapter().inspect(source)
    assert info["sections"] == ["Contents/section0.xml", "Contents/section1.xml"]
    assert [item["locator"] for item in info["paragraph_details"]] == [
        {"part": "Contents/section0.xml", "paragraph_id": "p-ko"},
        {"part": "Contents/section0.xml", "paragraph_id": "p-field"},
        {"part": "Contents/section0.xml", "paragraph_id": "cell-p"},
        {"part": "Contents/section1.xml", "paragraph_id": "p-en"},
    ]
    assert info["field_details"][0]["key"] == "customer"
    assert info["field_details"][0]["kind"] == "press"
    assert info["table_details"][0]["table_id"] == "orders"
    assert info["cell_details"][0]["column_span"] == 2
    assert info["fonts"][0]["face"] == "\ud568\ucd08\ub86c"
    assert info["styles"][0]["name"] == "Body"
    assert info["masters"] == ["Contents/masterPage0.xml"]
    assert info["headers"] == ["Contents/masterPage0.xml"]
    assert info["footers"] == ["Contents/masterPage0.xml"]
    assert info["mimetype_first_stored"] is True


def test_paragraph_and_single_text_edits_are_bounded(tmp_path: Path) -> None:
    source = _package(tmp_path / "source.hwpx")
    paragraph_out = tmp_path / "paragraph.hwpx"
    _ = HwpxAdapter().patch_paragraph_text(
        source,
        paragraph_out,
        ParagraphLocator("Contents/section1.xml", "p-en"),
        "\ub450 \ubc88\uc9f8 section",
        expected_text="Second section",
    )
    before, after = _hashes(source), _hashes(paragraph_out)
    assert {name for name in before if before[name] != after[name]} == {"Contents/section1.xml"}

    text_out = tmp_path / "text.hwpx"
    _ = HwpxAdapter().patch_text(
        source,
        text_out,
        TextLocator("Contents/section0.xml", "p-ko", 0, 1),
        "World",
        expected_text="English",
    )
    with zipfile.ZipFile(text_out) as archive:
        xml = archive.read("Contents/section0.xml")
    assert b">World</hp:t>" in xml and b'charPrIDRef="7"' in xml


def test_real_press_field_and_spanned_cell_edits_preserve_structure(tmp_path: Path) -> None:
    source = _package(tmp_path / "source.hwpx")
    field_out = tmp_path / "field.hwpx"
    evidence = HwpxAdapter().patch_field(source, field_out, "customer", "\ud64d\uae38\ub3d9", expected_text="\uace0\uac1d\uba85")
    assert evidence["field_id"] == "f-1" and evidence["field_kind"] == "press"

    cell_out = tmp_path / "cell.hwpx"
    _ = HwpxAdapter().patch_cell_text(
        source,
        cell_out,
        CellLocator("Contents/section0.xml", "orders", row=0, column=0),
        "\uc0c1\ud488 B",
        expected_text="\uc0c1\ud488 A",
    )
    with zipfile.ZipFile(cell_out) as archive:
        xml = archive.read("Contents/section0.xml")
    assert b'colSpan="2" rowSpan="1"' in xml
    assert b'styleIDRef="8"' in xml and "\uc0c1\ud488 B".encode() in xml


def test_atomic_derivation_is_hash_bound_and_exact(tmp_path: Path) -> None:
    source = _package(tmp_path / "source.hwpx")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "derived.hwpx"
    result = HwpxAdapter().derive_template(
        source,
        output,
        {"customer": {"value": "Ada & \ud64d", "expected_text": "\uace0\uac1d\uba85"}},
        expected_source_sha256=digest,
    )
    assert result["bindings"] == {"customer": "f-1"}
    assert result["source_sha256"] == digest
    assert _hashes(source)["BinData/opaque.bin"] == _hashes(output)["BinData/opaque.bin"]


def _unchanged(xml: bytes) -> bytes:
    return xml


def _stale_field_end(xml: bytes) -> bytes:
    return xml.replace(b'beginIDRef="f-1"', b'beginIDRef="stale"')


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (_unchanged, DocumentErrorCode.AMBIGUOUS_LOCATOR),
        (_stale_field_end, DocumentErrorCode.PACKAGE_INVALID),
    ],
)
def test_ambiguous_or_malformed_real_fields_are_refused_without_output(
    tmp_path: Path,
    mutation: Callable[[bytes], bytes],
    code: DocumentErrorCode,
) -> None:
    section = mutation(SECTION0)
    if code is DocumentErrorCode.AMBIGUOUS_LOCATOR:
        section = section.replace(b'</hp:p>', b'</hp:p><hp:field id="customer"><hp:t>x</hp:t></hp:field>', 1)
    source, output = _package(tmp_path / "bad.hwpx", section0=section), tmp_path / "out.hwpx"
    with pytest.raises(DocumentError) as caught:
        _ = HwpxAdapter().patch_field(source, output, "customer", "new")
    assert caught.value.code is code and not output.exists()


def test_stale_cell_and_binary_hwp_identity_are_truthfully_refused(tmp_path: Path) -> None:
    source, output = _package(tmp_path / "source.hwpx"), tmp_path / "out.hwpx"
    with pytest.raises(DocumentError) as caught:
        _ = HwpxAdapter().patch_cell_text(
            source,
            output,
            CellLocator("Contents/section0.xml", "orders", row=0, column=0),
            "new",
            expected_text="stale",
        )
    assert caught.value.code is DocumentErrorCode.PRECONDITION_FAILED and not output.exists()

    binary = tmp_path / "legacy.hwp"
    _ = binary.write_bytes(bytes.fromhex("d0cf11e0a1b11ae1") + b"legacy binary hwp")
    with pytest.raises(DocumentError) as unsupported:
        _ = HwpxAdapter().inspect(binary)
    assert unsupported.value.code is DocumentErrorCode.UNSUPPORTED_FORMAT
