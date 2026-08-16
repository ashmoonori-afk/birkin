from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

import pytest

from birkin.office.active_content_consent import (
    inspect_active_content,
    verify_preserved,
)
from birkin.office.adapters.docx import DocxAdapter
from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.service import DocumentService


def _artifact(path: Path) -> dict[str, str]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"content_hash": digest, "uri": str(path)}


def _package(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def _docx(path: Path, *, active: bool = True) -> Path:
    entries = {
        "[Content_Types].xml": (
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<Override PartName="/word/document.xml" '
            b'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
        ),
        "word/document.xml": (
            b'<w:document xmlns:w="urn:w"><w:p><w:sdt><w:sdtPr>'
            b'<w:tag w:val="customer"/></w:sdtPr><w:sdtContent><w:r>'
            b'<w:t>OLD</w:t></w:r></w:sdtContent></w:sdt></w:p></w:document>'
        ),
    }
    if active:
        entries |= {
            "word/vbaProject.bin": b"VBA-SENTINEL",
            "word/embeddings/oleObject1.bin": b"OLE-SENTINEL",
            "word/_rels/document.xml.rels": (
                b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rExt" '
                b'Type="ddeLink" Target="https://invalid.example/data" '
                b'TargetMode="External"/></Relationships>'
            ),
            "_xmlsignatures/sig1.xml": b'<Signature xmlns="urn:sig">SIGNED</Signature>',
        }
    return _package(path, entries)


def _xlsx(path: Path) -> Path:
    return _package(path, {
        "[Content_Types].xml": (
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            b'content-types"/>'
        ),
        "xl/workbook.xml": b'<workbook xmlns="urn:x"><sheets/></workbook>',
        "xl/worksheets/sheet1.xml": b'<worksheet xmlns="urn:x"><f>cmd|\' /C calc\'!A0</f></worksheet>',
        "xl/macrosheets/sheet1.xml": b'<worksheet xmlns="urn:x"/>',
        "xl/vbaProject.bin": b"VBA",
        "xl/activeX/activeX1.bin": b"ACTIVEX",
        "xl/_rels/workbook.xml.rels": (
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" '
            b'Type="externalLink" Target="externalLinks/externalLink1.xml"/>'
            b'<Relationship Id="r2" Type="externalLinkPath" '
            b'Target="file:///tmp/source.xlsx" TargetMode="External"/></Relationships>'
        ),
        "xl/externalLinks/externalLink1.xml": b'<externalLink xmlns="urn:x"/>',
    })


def _pptx(path: Path) -> Path:
    return _package(path, {
        "[Content_Types].xml": (
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            b'content-types"/>'
        ),
        "ppt/slides/slide1.xml": b'<p:sld xmlns:p="urn:p"><p:sp><p:nvPr><p:ph idx="7"/></p:nvPr><a:t xmlns:a="urn:a">OLD</a:t></p:sp></p:sld>',
        "ppt/vbaProject.bin": b"VBA",
        "ppt/activeX/activeX1.bin": b"ACTIVEX",
    })


def _hwpx(path: Path) -> Path:
    return _package(path, {
        "mimetype": b"application/hwp+zip",
        "Contents/section0.xml": b'<hp:section xmlns:hp="urn:h"><hp:field id="customer"><hp:t>OLD</hp:t></hp:field></hp:section>',
        "Scripts/macro.bin": b"MACRO",
        "BinData/ole1.bin": b"OLE",
    })


def _pdf(path: Path) -> Path:
    _ = path.write_bytes(b"%PDF-1.7\n1 0 obj << /OpenAction 2 0 R /Encrypt 3 0 R >> endobj\n2 0 obj << /S /JavaScript /JS (x) >> endobj\n3 0 obj << /Type /Sig /ByteRange [0 1 2 3] >> endobj\n%%EOF")
    return path


Builder = Callable[[Path], Path]


@pytest.mark.parametrize("builder,suffix", [
    (_docx, "docx"), (_xlsx, "xlsx"), (_xlsx, "xlsm"),
    (_pptx, "pptx"), (_pdf, "pdf"), (_hwpx, "hwpx"),
])
def test_real_files_return_deterministic_hash_bound_inventory(tmp_path: Path, builder: Builder, suffix: str) -> None:
    source = builder(tmp_path / f"risky.{suffix}")
    first = inspect_active_content(source)
    second = inspect_active_content(source)
    assert first == second
    assert first["source_sha256"] == _artifact(source)["content_hash"]
    assert first["inventory_sha256"] == second["inventory_sha256"]
    assert first["inventory"]
    assert all(set(item) == {"kind", "part", "relationship", "sha256", "risk"} for item in first["inventory"])


def _apply(service: DocumentService, source: Path, consent: object = None, output: str = "draft.docx") -> dict[str, object]:
    patch: dict[str, object] = {"operations": [{"field": "customer", "value": "Ada"}]}
    if consent is not None:
        patch["active_content_consent"] = consent
    return service.apply_document_patch(
        _artifact(source), patch,
        expected_source_sha256=_artifact(source)["content_hash"],
        output_name=output, dry_run=False,
    )


def test_risky_edit_default_denies_boolean_and_stale_consent(tmp_path: Path) -> None:
    service = DocumentService(tmp_path)
    source = _docx(tmp_path / "risky.docx")
    evidence = inspect_active_content(source)
    bad = [None, True, {
        "source_sha256": evidence["source_sha256"],
        "inventory_sha256": "0" * 64,
        "preservation_mode": "preserve_exact",
    }, {
        "source_sha256": "0" * 64,
        "inventory_sha256": evidence["inventory_sha256"],
        "preservation_mode": "preserve_exact",
    }, {
        "source_sha256": evidence["source_sha256"],
        "inventory_sha256": evidence["inventory_sha256"],
        "preservation_mode": "remove",
    }]
    for index, consent in enumerate(bad):
        with pytest.raises(DocumentError) as caught:
            _ = _apply(service, source, consent, f"denied-{index}.docx")
        assert caught.value.code in {
            DocumentErrorCode.POLICY_DENIED,
            DocumentErrorCode.INVALID_INPUT,
            DocumentErrorCode.UNSUPPORTED_EDIT,
            DocumentErrorCode.SOURCE_CHANGED,
        }
        assert not (tmp_path / "artifacts" / "drafts" / f"denied-{index}.docx").exists()


def test_exact_preserve_consent_succeeds_with_unchanged_hash_evidence(tmp_path: Path) -> None:
    service = DocumentService(tmp_path)
    source = _docx(tmp_path / "risky.docx")
    before = source.read_bytes()
    evidence = inspect_active_content(source)
    consent = {
        "source_sha256": evidence["source_sha256"],
        "inventory_sha256": evidence["inventory_sha256"],
        "preservation_mode": "preserve_exact",
    }
    result = _apply(service, source, consent)
    artifact = cast("Mapping[str, object]", result["draft_artifact"])
    output = Path(cast(str, artifact["uri"]))
    assert source.read_bytes() == before
    assert inspect_active_content(output)["inventory_sha256"] == evidence["inventory_sha256"]
    active_evidence = cast("Mapping[str, object]", result["active_content_evidence"])
    assert active_evidence["preserved"] is True


def test_exact_preservation_hashes_arbitrarily_named_internal_relationship_payload(
    tmp_path: Path,
) -> None:
    relationship = (
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rPayload" '
        b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject" '
        b'Target="../custom/innocent-name.dat"/></Relationships>'
    )
    source = _package(
        tmp_path / "source.docx",
        {
            "word/document.xml": b"<document/>",
            "word/_rels/document.xml.rels": relationship,
            "custom/innocent-name.dat": b"ACTIVE-PAYLOAD-A",
        },
    )
    changed = _package(
        tmp_path / "changed.docx",
        {
            "word/document.xml": b"<document/>",
            "word/_rels/document.xml.rels": relationship,
            "custom/innocent-name.dat": b"ACTIVE-PAYLOAD-B",
        },
    )

    evidence = inspect_active_content(source)
    assert evidence["inventory"][0]["sha256"] == hashlib.sha256(
        b"ACTIVE-PAYLOAD-A"
    ).hexdigest()
    with pytest.raises(DocumentError) as caught:
        _ = verify_preserved(evidence, changed)
    assert caught.value.code is DocumentErrorCode.POLICY_DENIED


def test_changed_active_part_is_deleted_and_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = DocumentService(tmp_path)
    source = _docx(tmp_path / "risky.docx")
    evidence = inspect_active_content(source)
    consent = {"source_sha256": evidence["source_sha256"], "inventory_sha256": evidence["inventory_sha256"], "preservation_mode": "preserve_exact"}
    original = DocxAdapter.patch_field

    def corrupt(
        self: DocxAdapter,
        src: Path,
        out: Path,
        key: str,
        value: str,
        *,
        expected_source_sha256: str | None = None,
    ) -> dict[str, object]:
        result = original(
            self, src, out, key, value,
            expected_source_sha256=expected_source_sha256,
        )
        with zipfile.ZipFile(out) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        entries["word/vbaProject.bin"] = b"CHANGED"
        _ = _package(out, entries)
        return result

    monkeypatch.setattr(DocxAdapter, "patch_field", corrupt)
    with pytest.raises(DocumentError) as caught:
        _ = _apply(service, source, consent)
    assert caught.value.code is DocumentErrorCode.POLICY_DENIED
    assert not (tmp_path / "artifacts" / "drafts" / "draft.docx").exists()
