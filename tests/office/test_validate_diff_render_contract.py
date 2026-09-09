from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import cast

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.service import DocumentService
from birkin.office.service_types import ArtifactRef
from birkin.tools import build_registry
from birkin.tools._types import ToolContext
from tests.office.fixture_builders import build_hwpx_template


def _artifact(path: Path) -> ArtifactRef:
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
    payloads: dict[str, dict[str, object]] = {
        "docx": {"paragraphs": ["Heading", "Same body"]},
        "xlsx": {"sheets": [{"name": "Data", "rows": [["Name", "Value"], ["Ada", 42]]}]},
        "pptx": {"slides": [{"title": "Heading", "body": "Same body"}]},
        "pdf": {"paragraphs": ["Heading", "Same body"]},
    }
    documents = {
        fmt: service.create_document(format=fmt, content=content, output_name=f"contract.{fmt}")["draft_artifact"]
        for fmt, content in payloads.items()
    }
    template = _artifact(build_hwpx_template(home / "contract-template.hwpx"))
    documents["hwpx"] = service.create_document(
        format="hwpx",
        content={"bindings": {"customer": "Same body"}},
        output_name="contract.hwpx",
        template=template,
    )["draft_artifact"]
    return documents


def test_validate_reports_six_independent_truthful_layers_for_real_files(tmp_path: Path) -> None:
    service = DocumentService(tmp_path)
    documents = _documents(service, tmp_path)
    allowed = {"pass", "fail", "warning", "unsupported", "not-run"}
    expected = {"schema", "package", "formula", "openability", "security", "fidelity"}

    for format_name, artifact in documents.items():
        result = service.validate_artifact(artifact)
        assert result["operation"] == "document_validate"
        assert result["format"] == format_name
        assert result["source_sha256"] == artifact["content_hash"]
        assert set(result["layers"]) == expected
        assert result["complete"] is False
        assert result["status"] != "pass"
        for name, layer in result["layers"].items():
            assert name == layer["name"]
            assert layer["status"] in allowed
            assert layer["validator"]
            assert layer["version"]
            assert layer["scope"]
            assert isinstance(layer["limits"], dict)
            assert isinstance(layer["findings"], list)


def test_diff_keeps_byte_semantic_package_and_visual_claims_distinct(tmp_path: Path) -> None:
    service = DocumentService(tmp_path)
    original = _documents(service, tmp_path)["docx"]
    source = Path(original["uri"])
    repacked = tmp_path / "repacked.docx"
    with zipfile.ZipFile(source) as incoming, zipfile.ZipFile(repacked, "w", zipfile.ZIP_DEFLATED) as outgoing:
        for name in reversed(incoming.namelist()):
            outgoing.writestr(name, incoming.read(name))
    comparison = service.compare_documents(original, _artifact(repacked))

    package = cast("dict[str, object]", comparison["package"])
    visual = cast("dict[str, object]", comparison["visual"])
    semantic = cast("dict[str, object]", comparison["semantic"])
    entries = cast("dict[str, list[dict[str, object]]]", package["entries"])
    limits = cast("dict[str, object]", semantic["limits"])
    assert comparison["byte_equal"] is False
    assert comparison["semantic_equal"] is True
    assert package["equal"] is True
    assert comparison["visual_equal"] is None
    assert visual["status"] == "unavailable"
    assert visual["visual_proof"] is False
    assert entries["unchanged"]
    assert all("bytes" not in entry for group in entries.values() for entry in group)
    assert limits["max_nodes_per_side"] == 1_000


@pytest.mark.parametrize("refusal", ["pdf"])
def test_render_is_bounded_semantic_preview_and_refuses_visual_outputs(
    tmp_path: Path, refusal: str
) -> None:
    service = DocumentService(tmp_path)
    artifact = _documents(service, tmp_path)["pdf"]
    before = Path(artifact["uri"]).read_bytes()
    preview = service.render_artifact(artifact, output_format="structured_preview")
    renderer = cast("dict[str, object]", preview["renderer"])
    extracted = cast("dict[str, object]", preview["preview"])
    receipt = cast("dict[str, object]", preview["receipt"])
    assert preview["render_kind"] == "structured_preview"
    assert preview["visual_proof"] is False
    assert renderer["used"] is False
    assert extracted["limits"] == {
        "max_spans": 100,
        "max_nodes": 100,
        "max_text_bytes": 20_000,
    }
    assert receipt["source_sha256"] == artifact["content_hash"]
    assert Path(artifact["uri"]).read_bytes() == before

    with pytest.raises(DocumentError) as unavailable:
        _ = service.render_artifact(artifact, output_format=refusal)
    assert unavailable.value.code is DocumentErrorCode.RENDER_UNAVAILABLE
    assert unavailable.value.artifact_sha256 == artifact["content_hash"]


@pytest.mark.parametrize("output_format", ["png", "thumbnail"])
def test_pdf_page_render_returns_a_hash_bound_png_artifact(
    tmp_path: Path, output_format: str
) -> None:
    service = DocumentService(tmp_path)
    artifact = _documents(service, tmp_path)["pdf"]
    result = service.render_artifact(artifact, output_format=output_format, page=1)
    output = cast("dict[str, object]", result["output_artifact"])
    renderer = cast("dict[str, object]", result["renderer"])
    quality = cast("dict[str, object]", result["quality_checks"])
    assert Path(cast("str", output["uri"])).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert result["visual_proof"] is True
    assert result["page_count"] == 1
    assert result["fonts"]
    assert quality["blank_page"] is False
    assert quality["edge_contact"] is False
    assert renderer == {"used": True, "name": "pypdfium2", "version": "4.30.0"}


def test_registered_tools_return_preview_and_structured_visual_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    office_home = tmp_path / "office"
    service = DocumentService(office_home)
    artifact = _documents(service, office_home)["docx"]
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"documents"})

    rendered = registry.execute(
        "render_artifact", {"artifact": artifact, "output_format": "structured_preview"}
    )
    assert not rendered.is_error
    preview = cast("dict[str, object]", json.loads(cast("str", rendered.content)))
    assert preview["evidence_class"] == "semantic_preview"

    refused = registry.execute(
        "render_artifact", {"artifact": artifact, "output_format": "png"}
    )
    assert refused.is_error
    body = cast("dict[str, object]", json.loads(cast("str", refused.content)))
    error = cast("dict[str, object]", body["error"])
    assert error["code"] == "RENDER_UNAVAILABLE"
