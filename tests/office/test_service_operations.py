from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from birkin.office.conversion_audit import LOSS_CATEGORIES
from birkin.office.service import DocumentService
from tests.office.fixture_builders import build_hwpx_template

LOSS_BUDGET = {category: 100 for category in LOSS_CATEGORIES}


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


@pytest.mark.parametrize(
    ("format_name", "content", "expected_text"),
    [
        (
            "docx",
            {"paragraphs": ["Quarterly report", "Revenue 42"]},
            "Revenue 42",
        ),
        (
            "xlsx",
            {
                "sheets": [
                    {
                        "name": "Summary",
                        "rows": [["Metric", "Value"], ["Revenue", 42]],
                    }
                ]
            },
            "Revenue",
        ),
        (
            "pptx",
            {"slides": [{"title": "Quarterly report", "body": "Revenue 42"}]},
            "Revenue 42",
        ),
        (
            "pdf",
            {"paragraphs": ["Quarterly report", "Revenue 42"]},
            "Revenue 42",
        ),
    ],
)
def test_create_validate_extract_and_convert_to_text(
    tmp_path: Path,
    format_name: str,
    content: dict[str, object],
    expected_text: str,
) -> None:
    service = DocumentService(tmp_path)
    created = service.create_document(
        format=format_name,
        content=content,
        output_name=f"quarterly.{format_name}",
    )
    artifact = created["draft_artifact"]
    assert Path(artifact["uri"]).is_file()

    validation = service.validate_artifact(artifact=artifact)
    assert validation["valid"] is True
    assert validation["source_sha256"] == artifact["content_hash"]
    assert validation["checks"]

    extracted = service.extract_document(source=artifact)
    assert expected_text in "\n".join(span["text"] for span in extracted["spans"])

    converted = service.convert_document(
        source=artifact,
        target_format="txt",
        output_name=f"{format_name}.txt",
        loss_budget=LOSS_BUDGET,
    )
    converted_path = Path(converted["draft_artifact"]["uri"])
    assert expected_text in converted_path.read_text(encoding="utf-8")


def test_hwpx_template_create_validates_and_converts_to_text(
    tmp_path: Path,
) -> None:
    service = DocumentService(tmp_path)
    template = _artifact(build_hwpx_template(tmp_path / "form-table.hwpx"))
    created = service.create_document(
        format="hwpx",
        content={"bindings": {"customer": "Ada"}},
        output_name="filled.hwpx",
        template=template,
    )
    artifact = created["draft_artifact"]
    assert service.validate_artifact(artifact=artifact)["valid"] is True

    converted = service.convert_document(
        source=artifact,
        target_format="txt",
        output_name="hwpx.txt",
        loss_budget=LOSS_BUDGET,
    )
    assert "Ada" in Path(converted["draft_artifact"]["uri"]).read_text(encoding="utf-8")
