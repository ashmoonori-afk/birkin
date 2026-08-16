from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from birkin.office.adapters.docx import DocxAdapter
from birkin.office.errors import DocumentError, DocumentErrorCode


def _package(path: Path, document: bytes, *, duplicate_control: bool = False) -> Path:
    if duplicate_control:
        control = (
            b'<w:sdt><w:sdtPr><w:tag w:val="customer"/></w:sdtPr>'
            b'<w:sdtContent><w:r><w:t>AB</w:t></w:r></w:sdtContent></w:sdt>'
        )
        document = document.replace(b"</w:body>", control + b"</w:body>")
    parts = {
        "[Content_Types].xml": b"<Types/>",
        "word/document.xml": document,
        "word/comments.xml": (
            b'<w:comments xmlns:w="w"><w:comment w:id="c1"/>'
            b'<w:comment w:id="c2"/><w:comment w:id="c3"/></w:comments>'
        ),
        "word/styles.xml": b'<w:styles xmlns:w="w"><w:style w:styleId="sentinel"/></w:styles>',
        "custom/unknown.bin": b"opaque-sentinel",
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in parts.items():
            info = zipfile.ZipInfo(name, (2025, 1, 2, 3, 4, 6))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return path


def _document() -> bytes:
    return b"""<w:document xmlns:w="w"><w:body>
<w:p><w:commentRangeStart w:id="c1"/><w:r><w:t>A</w:t></w:r>
<w:commentRangeStart w:id="c2"/><w:r><w:t>B</w:t></w:r><w:commentRangeEnd w:id="c1"/></w:p>
<w:p><w:r><w:t>C</w:t></w:r><w:commentRangeEnd w:id="c2"/>
<w:bookmarkStart w:id="1" w:name="zero"/><w:bookmarkEnd w:id="1"/>
<w:bookmarkStart w:id="9"/><w:bookmarkEnd w:id="9"/>
<w:bookmarkStart w:id="9"/><w:bookmarkEnd w:id="9"/>
<w:bookmarkStart/><w:r><w:t>missing id</w:t></w:r></w:p>
<w:p><w:ins w:id="10"><w:r><w:rPr><w:b/></w:rPr><w:t>in</w:t></w:r><w:r><w:t>sert</w:t></w:r></w:ins>
<w:del w:id="11"><w:r><w:delText>old</w:delText></w:r></w:del>
<w:moveFrom w:id="12"><w:r><w:t>move</w:t></w:r></w:moveFrom>
<w:ins w:id="13"><w:del w:id="14"><w:r><w:delText>nested</w:delText></w:r></w:del></w:ins></w:p>
<w:p><w:fldSimple w:instr="customerField"><w:r><w:t>OLD</w:t></w:r></w:fldSimple>
<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> DATE </w:instrText></w:r>
<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>result</w:t></w:r>
<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>
<w:sdt><w:sdtPr><w:tag w:val="customer"/></w:sdtPr><w:sdtContent>
<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>A</w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>B</w:t></w:r></w:p>
</w:sdtContent></w:sdt>
<w:sdt><w:sdtPr><w:tag w:val="cross"/></w:sdtPr><w:sdtContent><w:p>
<w:r><w:t>X</w:t></w:r><w:commentRangeStart w:id="c3"/><w:r><w:t>Y</w:t></w:r><w:commentRangeEnd w:id="c3"/>
</w:p></w:sdtContent></w:sdt>
<w:sdt><w:sdtPr><w:tag w:val="revision"/></w:sdtPr><w:sdtContent><w:ins w:id="20"><w:r><w:t>R</w:t></w:r></w:ins></w:sdtContent></w:sdt>
<w:tbl><w:tr><w:tc><w:sdt><w:sdtPr><w:tag w:val="table"/></w:sdtPr><w:sdtContent><w:r><w:t>T</w:t></w:r></w:sdtContent></w:sdt></w:tc></w:tr></w:tbl>
</w:body></w:document>"""


def _hashes(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}


def test_inspect_inventories_fragmented_ranges_fields_revisions_and_malformed_states(
    tmp_path: Path,
) -> None:
    source = _package(tmp_path / "structures.docx", _document())
    first = DocxAdapter().inspect(source)
    second = DocxAdapter().inspect(source)

    assert first["structures"] == second["structures"]
    tracked = first["tracked_changes"]
    fields = first["fields"]
    comments = first["comment_ranges"]
    bookmarks = first["bookmarks"]
    structures = first["structures"]
    assert {item["type"] for item in tracked} >= {"ins", "del", "moveFrom"}
    assert {item["type"] for item in fields} == {"simple", "complex"}
    assert any(item["range"].get("cross_paragraph", False) for item in comments)
    assert any(item["range"].get("zero_length", False) for item in bookmarks)
    assert any(item["state"] == "malformed" for item in bookmarks)
    assert any(item["state"] == "unsupported" for item in tracked)
    assert all({"stable_id", "id", "type", "part", "state", "range"} <= item.keys()
               for item in structures)
    orders = [item["order"] for item in first["boundaries"]]
    assert orders == sorted(orders)


def test_bounded_fragmented_edit_preserves_markup_unknown_parts_and_source_digest(
    tmp_path: Path,
) -> None:
    source = _package(tmp_path / "source.docx", _document())
    output = tmp_path / "output.docx"
    before = _hashes(source)
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()

    evidence = DocxAdapter().patch_field(
        source, output, "customer", "Ada", expected_text="AB",
        expected_source_sha256=source_digest,
    )

    after = _hashes(output)
    assert evidence["source_sha256"] == source_digest
    assert evidence["target_type"] == "content_control"
    assert before["custom/unknown.bin"] == after["custom/unknown.bin"]
    assert before["word/comments.xml"] == after["word/comments.xml"]
    with zipfile.ZipFile(output) as archive:
        xml = archive.read("word/document.xml")
    assert b"<w:rPr><w:b/></w:rPr>" in xml and b"<w:rPr><w:i/></w:rPr>" in xml
    assert b"<w:ins w:id=\"10\">" in xml and b"<w:bookmarkStart" in xml


def test_simple_field_result_can_be_edited_without_changing_instruction(tmp_path: Path) -> None:
    source = _package(tmp_path / "source.docx", _document())
    output = tmp_path / "output.docx"
    evidence = DocxAdapter().patch_field(
        source, output, "customerField", "NEW", expected_text="OLD"
    )
    with zipfile.ZipFile(output) as archive:
        xml = archive.read("word/document.xml")
    assert b'w:instr="customerField"' in xml and b">NEW</w:t>" in xml
    assert evidence["target_type"] == "simple_field"


@pytest.mark.parametrize("key", ["cross", "revision", "table"])
def test_bounded_edit_refuses_cross_range_revision_and_table_targets(
    tmp_path: Path, key: str
) -> None:
    source = _package(tmp_path / "source.docx", _document())
    output = tmp_path / "output.docx"
    with pytest.raises(DocumentError) as caught:
        _ = DocxAdapter().patch_field(source, output, key, "changed")
    assert caught.value.code is DocumentErrorCode.UNSUPPORTED_EDIT
    assert not output.exists()


def test_bounded_edit_refuses_duplicate_stale_and_tracked_change_mutation(tmp_path: Path) -> None:
    source = _package(tmp_path / "source.docx", _document(), duplicate_control=True)
    output = tmp_path / "output.docx"
    with pytest.raises(DocumentError) as duplicate:
        _ = DocxAdapter().patch_field(source, output, "customer", "changed")
    assert duplicate.value.code is DocumentErrorCode.AMBIGUOUS_LOCATOR
    clean = _package(tmp_path / "clean.docx", _document())
    with pytest.raises(DocumentError) as stale:
        _ = DocxAdapter().patch_field(clean, output, "customer", "changed", expected_text="stale")
    assert stale.value.code is DocumentErrorCode.PRECONDITION_FAILED
    with pytest.raises(DocumentError) as tracked:
        DocxAdapter().patch_tracked_change(clean, output, "10", action="accept")
    assert tracked.value.code is DocumentErrorCode.UNSUPPORTED_EDIT
    assert not output.exists()
