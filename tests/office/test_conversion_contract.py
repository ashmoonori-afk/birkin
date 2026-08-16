from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import cast

import pytest

from birkin.office.conversion_audit import LOSS_CATEGORIES
from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.service import DocumentService
from birkin.office.service_create import convert_document
from birkin.office.service_types import ArtifactRef
from birkin.office.service_workspace import DocumentWorkspace
from birkin.tools import build_registry
from birkin.tools._types import ToolContext
from tests.office.fixture_builders import build_hwpx_template


def _budget(limit: int = 10_000) -> dict[str, int]:
    return {category: limit for category in LOSS_CATEGORIES}


def _artifact(path: Path) -> dict[str, str]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "artifact_id": digest,
        "content_hash": digest,
        "media_type": "application/octet-stream",
        "uri": str(path),
        "sensitivity": "internal",
        "acl_fingerprint": "a" * 64,
    }


def _documents(service: DocumentService, home: Path) -> dict[str, ArtifactRef]:
    plans: dict[str, dict[str, object]] = {
        "docx": {"paragraphs": ["Quarterly report", "Revenue 42"]},
        "xlsx": {"sheets": [{"name": "Summary", "rows": [["Revenue", 42]]}]},
        "pptx": {"slides": [{"title": "Quarterly report", "body": "Revenue 42"}]},
        "pdf": {"paragraphs": ["Quarterly report", "Revenue 42"]},
    }
    artifacts = {
        fmt: service.create_document(
            format=fmt, content=content, output_name=f"source.{fmt}"
        )["draft_artifact"]
        for fmt, content in plans.items()
    }
    template = _artifact(build_hwpx_template(home / "source-template.hwpx"))
    artifacts["hwpx"] = service.create_document(
        format="hwpx",
        content={"bindings": {"customer": "Revenue 42"}},
        output_name="source.hwpx",
        template=template,
    )["draft_artifact"]
    return artifacts


@pytest.mark.parametrize("format_name", ["docx", "xlsx", "pptx", "pdf", "hwpx"])
def test_real_file_text_conversion_is_budget_bound_and_receipted(
    tmp_path: Path, format_name: str
) -> None:
    service = DocumentService(tmp_path)
    artifact = _documents(service, tmp_path)[format_name]
    before = Path(artifact["uri"]).read_bytes()
    result = convert_document(
        DocumentWorkspace(tmp_path),
        artifact,
        target_format="txt",
        output_name=f"converted-{format_name}.txt",
        extract=service.extract_document,
        loss_budget=_budget(),
    )
    output = Path(result["draft_artifact"]["uri"])
    receipt = result["receipt"]
    assert "Revenue" in output.read_text(encoding="utf-8")
    assert Path(artifact["uri"]).read_bytes() == before
    assert hashlib.sha256(output.read_bytes()).hexdigest() == result["output_sha256"]
    assert receipt["source_sha256"] == artifact["content_hash"]
    assert receipt["output_sha256"] == result["output_sha256"]
    assert receipt["engine"]["name"] == "birkin-text-projection"
    assert receipt["sandbox"] == {
        "network_accessed": False,
        "active_content_executed": False,
        "external_content_fetched": False,
        "source_immutable": True,
    }
    assert set(receipt["loss_budget"]) == set(LOSS_CATEGORIES)
    assert receipt["validation"]["passed"] is True
    assert receipt["diff"]["text_equal"] is True


def test_tool_requires_budget_and_receipt_is_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    service = DocumentService(tmp_path)
    artifact = service.create_document(
        format="docx", content={"paragraphs": ["Stable text"]}, output_name="in.docx"
    )["draft_artifact"]
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"documents"})
    base = {"source": artifact, "target_format": "txt", "output_name": "out.txt"}
    missing = registry.execute("convert_document", base)
    assert missing.is_error
    assert json.loads(cast(str, missing.content))["error"]["code"] == "INVALID_INPUT"
    payload = {**base, "loss_budget": _budget()}
    first = registry.execute("convert_document", payload)
    assert not first.is_error
    first_body = cast("dict[str, object]", json.loads(cast(str, first.content)))
    first_artifact = cast("dict[str, str]", first_body["draft_artifact"])
    collision = registry.execute("convert_document", payload)
    collision_body = cast(
        "dict[str, dict[str, object]]", json.loads(cast(str, collision.content))
    )
    assert collision_body["error"]["code"] == "OUTPUT_EXISTS"
    Path(first_artifact["uri"]).unlink()
    second = registry.execute("convert_document", payload)
    assert json.loads(cast(str, second.content))["receipt"] == first_body["receipt"]


def test_refusals_leave_destination_unpublished(tmp_path: Path) -> None:
    service = DocumentService(tmp_path)
    artifact = service.create_document(
        format="docx", content={"paragraphs": ["text"]}, output_name="plain.docx"
    )["draft_artifact"]
    workspace = DocumentWorkspace(tmp_path)
    cases: list[tuple[dict[str, int], str, DocumentErrorCode]] = [
        ({}, "budget.txt", DocumentErrorCode.LOSSY_WRITE_BLOCKED),
        (_budget(), "../escape.txt", DocumentErrorCode.INVALID_INPUT),
    ]
    for budget, name, code in cases:
        with pytest.raises(DocumentError) as caught:
            _ = convert_document(
                workspace,
                artifact,
                target_format="txt",
                output_name=name,
                extract=service.extract_document,
                loss_budget=budget,
            )
        assert caught.value.code is code
        assert not (workspace.drafts / name).exists()
    with pytest.raises(DocumentError) as unsupported:
        _ = convert_document(
            workspace,
            artifact,
            target_format="docx",
            output_name="native.docx",
            extract=service.extract_document,
            loss_budget=_budget(),
        )
    assert unsupported.value.code is DocumentErrorCode.CAPABILITY_UNAVAILABLE


def test_validation_failure_cleans_temporary_and_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = DocumentService(tmp_path)
    artifact = service.create_document(
        format="docx", content={"paragraphs": ["text"]}, output_name="validate.docx"
    )["draft_artifact"]
    workspace = DocumentWorkspace(tmp_path)
    original = Path.read_bytes

    def corrupt_temporary(path: Path) -> bytes:
        data = original(path)
        if path.parent == workspace.drafts and path.suffix == ".txt":
            return b"corrupt"
        return data

    monkeypatch.setattr(Path, "read_bytes", corrupt_temporary)
    with pytest.raises(DocumentError) as caught:
        _ = convert_document(
            workspace, artifact, target_format="txt", output_name="invalid.txt",
            extract=service.extract_document, loss_budget=_budget(),
        )
    assert caught.value.code is DocumentErrorCode.VALIDATION_FAILED
    assert list(workspace.drafts.glob("*.txt")) == []


@pytest.mark.parametrize("marker", [b"/Encrypt 1 0 R", b"/Type /Sig /ByteRange [0 1 2 3]"])
def test_pdf_encryption_and_signatures_are_refused(
    tmp_path: Path, marker: bytes
) -> None:
    service = DocumentService(tmp_path)
    artifact = service.create_document(
        format="pdf", content={"paragraphs": ["text"]}, output_name="secured.pdf"
    )["draft_artifact"]
    source = Path(artifact["uri"])
    _ = source.write_bytes(
        source.read_bytes().replace(b"%%EOF", marker + b"\n%%EOF")
    )
    secured = _artifact(source)
    with pytest.raises(DocumentError) as caught:
        _ = convert_document(
            DocumentWorkspace(tmp_path), secured, target_format="txt",
            output_name="secured.txt", extract=service.extract_document,
            loss_budget=_budget(),
        )
    assert caught.value.code is DocumentErrorCode.POLICY_DENIED
    assert not (tmp_path / "artifacts" / "drafts" / "secured.txt").exists()


def test_active_content_is_refused_even_with_budget(tmp_path: Path) -> None:
    source = tmp_path / "active.docx"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<Override PartName="/word/document.xml" '
            b'ContentType="application/vnd.openxmlformats-officedocument.'
            b'wordprocessingml.document.main+xml"/></Types>',
        )
        archive.writestr("word/document.xml", b'<w:document xmlns:w="w"><w:p><w:t>x</w:t></w:p></w:document>')
        archive.writestr("word/vbaProject.bin", b"not executed")
    artifact = _artifact(source)
    service = DocumentService(tmp_path)
    with pytest.raises(DocumentError) as caught:
        _ = convert_document(
            DocumentWorkspace(tmp_path), artifact, target_format="txt",
            output_name="active.txt", extract=service.extract_document,
            loss_budget=_budget(),
        )
    assert caught.value.code is DocumentErrorCode.POLICY_DENIED
    assert not (tmp_path / "artifacts" / "drafts" / "active.txt").exists()
