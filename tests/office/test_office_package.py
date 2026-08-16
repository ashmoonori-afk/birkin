import hashlib
import stat
import zipfile

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.limits import PackageLimits
from birkin.office.package import clone_package, preflight_package


def _zip(path, entries):
    with zipfile.ZipFile(path,'w') as z:
        for name,data in entries:
            z.writestr(name,data)
def test_clone_replaces_one_known_part_and_preserves_unknown_part_bytes(tmp_path):
    src=tmp_path/'source.docx'
    _zip(src,[('[Content_Types].xml',b'<Types/>'),('word/document.xml',b'<doc>old</doc>'),('custom/opaque.bin',b'\x00opaque')])
    before=hashlib.sha256(src.read_bytes()).hexdigest()
    out=tmp_path/'draft.docx'
    manifest=clone_package(src,out,{'word/document.xml':b'<doc>new</doc>'})
    with zipfile.ZipFile(out) as z:
        assert z.read('custom/opaque.bin')==b'\x00opaque' and z.read('word/document.xml')==b'<doc>new</doc>'
    assert manifest['parts']['custom/opaque.bin']['original_sha256']==hashlib.sha256(b'\x00opaque').hexdigest()
    assert hashlib.sha256(src.read_bytes()).hexdigest()==before
def test_preflight_rejects_traversal_and_dtd_with_typed_codes(tmp_path):
    for name,entries in [('bad.docx',[('../evil',b'x')]),('dtd.docx',[('word/document.xml',b'<!DOCTYPE x><x/>')])]:
        path=tmp_path/name
        _zip(path,entries)
        with pytest.raises(DocumentError) as caught:
            preflight_package(path)
        assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID


def test_preflight_rejects_special_entries(tmp_path):
    special = tmp_path / "special.docx"
    with zipfile.ZipFile(special, "w") as archive:
        info = zipfile.ZipInfo("word/link.xml")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, b"document.xml")
    with pytest.raises(DocumentError, match="special"):
        preflight_package(special)


def test_preflight_rejects_high_compression_ratio(tmp_path):
    bomb = tmp_path / "bomb.docx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"A" * 4096)
    limits = PackageLimits(
        max_entries=10,
        max_uncompressed_bytes=10_000,
        max_entry_ratio=2,
    )
    with pytest.raises(DocumentError, match="ratio"):
        preflight_package(bomb, limits)


def test_preflight_reports_external_relationships_and_active_content(tmp_path):
    source = tmp_path / "active.docx"
    relationships = b"""\
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="attachedTemplate"
    Target="https://attacker.invalid/template.dotm" TargetMode="External"/>
</Relationships>
"""
    _zip(
        source,
        [
            ("word/document.xml", b"<document/>"),
            ("word/_rels/document.xml.rels", relationships),
            ("word/vbaProject.bin", b"macro"),
        ],
    )
    manifest = preflight_package(source)
    assert manifest["external_relationships"] == [
        {
            "part_uri": "word/_rels/document.xml.rels",
            "relationship_id": "rId1",
            "target": "https://attacker.invalid/template.dotm",
        }
    ]
    assert manifest["active_content"] == [
        {"part_uri": "word/vbaProject.bin", "kind": "macro"}
    ]
