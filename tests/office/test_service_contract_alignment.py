from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import cast

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.service import DocumentService
from tests.office.fixture_builders import build_docx_template
from tests.office.korean_fixtures import build_pdf


def _artifact(path: Path, digest: str | None = None) -> dict[str, str]:
    return {
        "uri": str(path),
        "content_hash": digest or hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _docx_fields() -> list[dict[str, object]]:
    return [{"key": "customer", "kind": "native", "field": "customer"}]


def _encrypted_hwpx(path: Path) -> Path:
    namespace = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
    manifest = f'''<manifest:manifest xmlns:manifest="{namespace}">
<manifest:file-entry manifest:full-path="Contents/section0.xml" manifest:size="1">
<manifest:encryption-data manifest:checksum-type="{namespace}#sha256-1k" manifest:checksum="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=">
<manifest:algorithm manifest:algorithm-name="http://www.w3.org/2001/04/xmlenc#aes256-cbc" manifest:initialisation-vector="AAAAAAAAAAAAAAAAAAAAAA=="/>
<manifest:key-derivation manifest:key-derivation-name="{namespace}#pbkdf2" manifest:key-size="32" manifest:iteration-count="1024" manifest:salt="AAAAAAAAAAAAAAAAAAAAAA=="/>
<manifest:start-key-generation manifest:start-key-generation-name="http://www.w3.org/2000/09/xmldsig#sha256" manifest:key-size="32"/>
</manifest:encryption-data></manifest:file-entry></manifest:manifest>'''.encode()
    content = (
        b'<opf:package xmlns:opf="http://www.idpf.org/2007/opf"><opf:manifest>'
        b'<opf:item id="sec0" href="section0.xml" media-type="application/xml"/>'
        b'</opf:manifest><opf:spine><opf:itemref idref="sec0"/></opf:spine>'
        b"</opf:package>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("mimetype", b"application/hwp+zip")
        archive.writestr("META-INF/manifest.xml", manifest)
        archive.writestr("Contents/content.hpf", content)
        archive.writestr("Contents/section0.xml", bytes(16))
    return path


def test_fill_template_consumes_verified_template_and_binds_plan_identity(
    tmp_path: Path,
) -> None:
    source = build_docx_template(tmp_path / "template.docx")
    reference = _artifact(source)

    result = DocumentService(tmp_path).fill_template(
        reference,
        [{"key": "customer", "value": "Ada"}],
        output_name="filled.docx",
    )

    assert result["status"] == "planned"
    assert result["format"] == "docx"
    assert result["source_sha256"] == reference["content_hash"]
    assert result["expected_source_sha256"] == reference["content_hash"]
    assert result["output_name"] == "filled.docx"
    assert result["operations"] == [{"field": "customer", "value": "Ada"}]
    assert result["patch"] == {"operations": result["operations"]}


def test_fill_template_refuses_template_outside_workspace_jail(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    source = build_docx_template(tmp_path / "outside.docx")

    with pytest.raises(DocumentError) as caught:
        _ = DocumentService(home).fill_template(
            _artifact(source),
            [{"key": "customer", "value": "Ada"}],
            output_name="filled.docx",
            fields=_docx_fields(),
        )

    assert caught.value.code is DocumentErrorCode.PERMISSION_DENIED


def test_fill_template_refuses_stale_template_hash(tmp_path: Path) -> None:
    source = build_docx_template(tmp_path / "template.docx")

    with pytest.raises(DocumentError) as caught:
        _ = DocumentService(tmp_path).fill_template(
            _artifact(source, "0" * 64),
            [{"key": "customer", "value": "Ada"}],
            output_name="filled.docx",
            fields=_docx_fields(),
        )

    assert caught.value.code is DocumentErrorCode.SOURCE_CHANGED


def test_fill_template_validates_output_name_against_template_format(
    tmp_path: Path,
) -> None:
    source = build_docx_template(tmp_path / "template.docx")

    with pytest.raises(DocumentError) as caught:
        _ = DocumentService(tmp_path).fill_template(
            _artifact(source),
            [{"key": "customer", "value": "Ada"}],
            output_name="../filled.pdf",
            fields=_docx_fields(),
        )

    assert caught.value.code is DocumentErrorCode.INVALID_INPUT


def test_fill_template_never_plans_unsupported_pdf_fill(tmp_path: Path) -> None:
    source = build_pdf(tmp_path / "form.pdf", "Hello PDF")

    with pytest.raises(DocumentError) as caught:
        _ = DocumentService(tmp_path).fill_template(
            _artifact(source),
            [{"key": "name", "value": "Ada"}],
            output_name="filled.pdf",
            fields=[{"key": "name", "kind": "native", "field": "name"}],
        )

    assert caught.value.code is DocumentErrorCode.UNSUPPORTED_EDIT


def test_fill_template_refuses_encrypted_hwpx_before_planning(tmp_path: Path) -> None:
    source = _encrypted_hwpx(tmp_path / "protected.hwpx")

    with pytest.raises(DocumentError) as caught:
        _ = DocumentService(tmp_path).fill_template(
            _artifact(source),
            [{"key": "customer", "value": "Ada"}],
            output_name="filled.hwpx",
            fields=_docx_fields(),
        )

    assert caught.value.code is DocumentErrorCode.CAPABILITY_UNAVAILABLE
    assert caught.value.details["reason"] == "unsupported_encryption_state"


def test_patch_dry_run_rejects_the_same_invalid_operation_count_as_execution(
    tmp_path: Path,
) -> None:
    source = build_docx_template(tmp_path / "template.docx")
    reference = _artifact(source)
    service = DocumentService(tmp_path)

    for dry_run in (True, False):
        with pytest.raises(DocumentError) as caught:
            _ = service.apply_document_patch(
                reference,
                {"operations": []},
                expected_source_sha256=reference["content_hash"],
                output_name=f"count-{dry_run}.docx",
                dry_run=dry_run,
            )
        assert caught.value.code is DocumentErrorCode.INVALID_INPUT


def test_patch_dry_run_rejects_the_same_shape_and_value_as_execution(
    tmp_path: Path,
) -> None:
    source = build_docx_template(tmp_path / "template.docx")
    reference = _artifact(source)
    service = DocumentService(tmp_path)
    invalid = (
        {"cell": "A1", "value": 1},
        {"field": "customer", "value": 1},
    )

    for index, operation in enumerate(invalid):
        for dry_run in (True, False):
            with pytest.raises(DocumentError) as caught:
                _ = service.apply_document_patch(
                    reference,
                    {"operations": [operation]},
                    expected_source_sha256=reference["content_hash"],
                    output_name=f"shape-{index}-{dry_run}.docx",
                    dry_run=dry_run,
                )
            assert caught.value.code is DocumentErrorCode.INVALID_INPUT


def test_patch_dry_run_refuses_read_only_pdf_capability(tmp_path: Path) -> None:
    source = build_pdf(tmp_path / "source.pdf", "Hello PDF")
    reference = _artifact(source)

    with pytest.raises(DocumentError) as caught:
        _ = DocumentService(tmp_path).apply_document_patch(
            reference,
            {"operations": [{"field": "name", "value": "Ada"}]},
            expected_source_sha256=reference["content_hash"],
            output_name="patched.pdf",
            dry_run=True,
        )

    assert caught.value.code is DocumentErrorCode.UNSUPPORTED_EDIT


def test_truncated_semantic_prefix_never_claims_equality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from birkin.office import diff

    left = tmp_path / "left.pdf"
    right = tmp_path / "right.pdf"
    _ = left.write_bytes(b"left")
    _ = right.write_bytes(b"right")

    def items(path: Path, _format: str) -> list[dict[str, object]]:
        tail = "left tail" if path == left else "right tail"
        return [
            {"text": "same prefix", "kind": "page_text", "locator": {}, "method": "test"},
            {"text": tail, "kind": "page_text", "locator": {}, "method": "test"},
        ]

    monkeypatch.setattr(diff, "extract_items", items)
    monkeypatch.setattr(diff, "MAX_SEMANTIC_NODES", 1)
    result = diff.compare_documents(left, right, "pdf", "pdf")

    assert result["semantic_equal"] is None
    semantic = cast("dict[str, object]", result["semantic"])
    assert semantic["status"] == "inconclusive"


