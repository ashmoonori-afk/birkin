from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from typing import cast

import pytest

from birkin.office.adapters.pdf import PdfAdapter
from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.service import DocumentService
from tests.office.korean_fixtures import build_pdf


def _artifact(path: Path) -> dict[str, str]:
    return {
        "uri": str(path),
        "content_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _adapter_refusal() -> DocumentError:
    return DocumentError(
        DocumentErrorCode.PERMISSION_DENIED,
        "extract",
        "state-aware PDF refusal",
        details={"reason": "pdf_password_required"},
    )


def test_public_pdf_extraction_routes_through_pdf_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = build_pdf(tmp_path / "source.pdf", "Hello PDF")

    def refuse(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise _adapter_refusal()

    monkeypatch.setattr(PdfAdapter, "extract", refuse)
    with pytest.raises(DocumentError) as caught:
        _ = DocumentService(tmp_path).extract_document(_artifact(source))
    assert caught.value.details["reason"] == "pdf_password_required"


def test_public_pdf_comparison_reports_pdf_adapter_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = build_pdf(tmp_path / "left.pdf", "Hello PDF")
    right = build_pdf(tmp_path / "right.pdf", "Hello PDF")

    def refuse(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise _adapter_refusal()

    monkeypatch.setattr(PdfAdapter, "extract", refuse)
    result = DocumentService(tmp_path).compare_documents(
        _artifact(left), _artifact(right)
    )
    semantic = cast("dict[str, object]", result["semantic"])
    assert semantic["status"] == "unavailable"
    assert semantic["reason"] == "state-aware PDF refusal"
    refusal = cast("dict[str, object]", semantic["refusal"])
    details = cast("dict[str, object]", refusal["details"])
    assert details["reason"] == "pdf_password_required"


def test_public_pdf_preview_routes_through_pdf_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = build_pdf(tmp_path / "source.pdf", "Hello PDF")

    def refuse(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise _adapter_refusal()

    monkeypatch.setattr(PdfAdapter, "extract", refuse)
    with pytest.raises(DocumentError) as caught:
        _ = DocumentService(tmp_path).render_artifact(
            _artifact(source), output_format="structured_preview"
        )
    assert caught.value.details["reason"] == "pdf_password_required"


def test_pdf_provenance_matches_wired_optional_backend() -> None:
    from birkin.office.adapters.catalog import adapter_inventory

    pdf = next(item for item in adapter_inventory() if item["format"] == "pdf")
    for operation in ("inspect", "extract"):
        capability = pdf["capabilities"][operation]
        assert capability["availability"] == "conditional"
        assert capability["integration_mode"] == "optional-python"
        assert capability["install_probe"] == "python-import:pypdf"
        assert "office-advanced" in capability["reason"]
    pypdf = next(item for item in pdf["packages"] if item["name"] == "pypdf")
    assert "wired" in pypdf["role"].lower()
    assert "not wired" not in pypdf["role"].lower()


def test_non_latin_pdf_creation_refuses_without_importing_reportlab(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_import = importlib.import_module

    def import_without_reportlab(name: str, package: str | None = None) -> object:
        if name.startswith("reportlab"):
            raise AssertionError("refused ReportLab path was executed")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", import_without_reportlab)
    with pytest.raises(DocumentError) as caught:
        _ = DocumentService(tmp_path).create_document(
            format="pdf",
            content={"paragraphs": ["분기 보고서"]},
            output_name="korean.pdf",
        )

    assert caught.value.code is DocumentErrorCode.CAPABILITY_UNAVAILABLE
    assert caught.value.details["reason"] == "pdf_non_latin_backend_unavailable"
    assert "install_hint" not in caught.value.details
    assert not (tmp_path / "artifacts" / "drafts" / "korean.pdf").exists()


def test_catalog_derives_runtime_and_tool_format_surfaces(tmp_path: Path) -> None:
    from birkin.office.adapters.catalog import adapter_inventory, supported_formats
    from birkin.office.extract import SUPPORTED_FORMATS
    from birkin.tools import build_registry
    from birkin.tools._types import ToolContext

    inventory_formats = tuple(item["format"] for item in adapter_inventory())
    assert supported_formats() == inventory_formats
    assert SUPPORTED_FORMATS == frozenset(supported_formats("extract"))

    registry = build_registry(
        ToolContext(cfg={}, client=None, cwd=tmp_path), include={"documents"}
    )
    create = next(spec for spec in registry.specs() if spec["name"] == "create_document")
    schema = cast("dict[str, object]", create["input_schema"])
    properties = cast("dict[str, object]", schema["properties"])
    format_schema = cast("dict[str, object]", properties["format"])
    assert format_schema["enum"] == list(supported_formats("create"))
