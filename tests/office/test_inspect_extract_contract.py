from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.service import DocumentService
from birkin.office.service_types import ArtifactRef
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
    created: dict[str, ArtifactRef] = {}
    payloads: dict[str, dict[str, object]] = {
        "docx": {"paragraphs": ["Heading", "Body text"]},
        "xlsx": {"sheets": [{"name": "Data", "rows": [["Name", "Value"], ["Ada", 42]]}]},
        "pptx": {"slides": [{"title": "Title", "body": "Slide body"}]},
        "pdf": {"paragraphs": ["PDF heading", "PDF body"]},
    }
    for format_name, content in payloads.items():
        result = service.create_document(
            format=format_name,
            content=content,
            output_name=f"sample.{format_name}",
        )
        created[format_name] = result["draft_artifact"]
    template = _artifact(build_hwpx_template(home / "sample-template.hwpx"))
    result = service.create_document(
        format="hwpx",
        content={"bindings": {"customer": "HWPX body"}},
        output_name="sample.hwpx",
        template=template,
    )
    created["hwpx"] = result["draft_artifact"]
    return created


def test_real_files_have_honest_inspect_and_extract_contract(tmp_path: Path) -> None:
    service = DocumentService(tmp_path)
    documents = _documents(service, tmp_path)
    expected_kinds = {
        "docx": "paragraph",
        "xlsx": "row",
        "pptx": "slide_paragraph",
        "pdf": "page_text",
        "hwpx": "paragraph",
    }

    for format_name, artifact in documents.items():
        inspected = service.inspect_document(source=artifact)
        assert inspected["format"] == format_name
        assert inspected["source"] == {
            "sha256": artifact["content_hash"],
            "locator": f"sha256:{artifact['content_hash']}",
        }
        size_bytes = cast("dict[str, object]", inspected["metadata"])["size_bytes"]
        assert isinstance(size_bytes, int) and size_bytes > 0
        assert cast("dict[str, object]", inspected["structure"])["inventory"]
        risk_inventory = cast("dict[str, object]", inspected["risks"])
        assert set(risk_inventory) == {
            "active_content",
            "external_relationships",
            "findings",
            "coverage",
        }
        adapter = cast("dict[str, object]", inspected["adapter"])
        assert adapter["format"] == format_name
        assert "extract" in cast("dict[str, object]", adapter["capabilities"])
        assert adapter["packages"]

        extracted = service.extract_document(
            source=artifact,
            max_spans=100,
            max_nodes=100,
            max_text_bytes=10_000,
        )
        assert extracted["source"] == inspected["source"]
        assert extracted["projection"] == "text"
        assert extracted["text"]
        assert extracted["spans"]
        assert extracted["nodes"]
        assert extracted["nodes"][0]["kind"] == expected_kinds[format_name]
        assert extracted["truncation"] == {"truncated": False, "reasons": []}
        assert extracted["limits"] == {
            "max_spans": 100,
            "max_nodes": 100,
            "max_text_bytes": 10_000,
        }
        assert set(extracted["unsupported"]) == {
            "tables",
            "forms",
            "images",
            "comments",
            "fields",
        }
        assert all(
            item["state"] in {"supported", "unsupported"}
            for item in extracted["unsupported"].values()
        )


def test_extract_limits_are_byte_bounded_and_report_truncation(tmp_path: Path) -> None:
    service = DocumentService(tmp_path)
    artifact = _documents(service, tmp_path)["docx"]
    result = service.extract_document(
        source=artifact, max_spans=1, max_nodes=1, max_text_bytes=4
    )
    assert len(result["text"].encode("utf-8")) <= 4
    assert len(result["spans"]) <= 1
    assert len(result["nodes"]) <= 1
    assert result["truncation"]["truncated"] is True
    assert result["truncation"]["reasons"]


def test_inspect_extract_refuse_outside_jail_identity_and_bad_limits(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    service = DocumentService(home)
    outside = tmp_path / "outside.docx"
    _ = outside.write_bytes(b"not a package")
    with pytest.raises(DocumentError) as jailed:
        _ = service.inspect_document(source=_artifact(outside))
    assert jailed.value.code is DocumentErrorCode.PERMISSION_DENIED

    disguised = home / "disguised.pdf"
    _ = disguised.write_bytes(b"PK\x03\x04not-pdf")
    with pytest.raises(DocumentError) as identity:
        _ = service.inspect_document(source=_artifact(disguised))
    assert identity.value.code is DocumentErrorCode.PACKAGE_INVALID

    valid = _documents(service, home)["docx"]
    with pytest.raises(DocumentError) as over_limit:
        _ = service.extract_document(source=valid, max_nodes=10_001)
    assert over_limit.value.code is DocumentErrorCode.INVALID_INPUT
