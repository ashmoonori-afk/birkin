from __future__ import annotations

import hashlib
import json
import shutil
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


@pytest.mark.skipif(
    not Path("C:/Windows/Fonts/malgun.ttf").exists(),
    reason="Windows Korean font validation requires Malgun Gothic",
)
def test_korean_pdf_creation_embeds_hash_bound_font_and_extracts_all_content(
    tmp_path: Path,
) -> None:
    font = tmp_path / "imports" / "malgun.ttf"
    font.parent.mkdir()
    _ = shutil.copy2("C:/Windows/Fonts/malgun.ttf", font)
    service = DocumentService(tmp_path)
    created = service.create_document(
        format="pdf",
        content={
            "paragraphs": ["분기 보고서 Quarter 3", "합계 123,456원"],
            "table": [["항목", "금액"], ["매출", "123,456"]],
            "font": _artifact(font),
        },
        output_name="korean.pdf",
    )
    extracted = service.extract_document(created["draft_artifact"])
    assert all(text in extracted["text"] for text in ("분기 보고서", "Quarter 3", "123,456", "항목", "매출"))

    from pypdf import PdfReader

    reader = PdfReader(created["draft_artifact"]["uri"])
    fonts = reader.pages[0]["/Resources"]["/Font"]

    def embedded(font_object: object) -> bool:
        raw = font_object.get_object()
        descriptors = [raw.get("/FontDescriptor")]
        descriptors.extend(
            descendant.get_object().get("/FontDescriptor")
            for descendant in raw.get("/DescendantFonts", [])
        )
        return any(
            descriptor is not None and "/FontFile2" in descriptor.get_object()
            for descriptor in descriptors
        )

    assert any(embedded(font_object) for font_object in fonts.values())


def test_catalog_derives_runtime_and_registered_read_surfaces(tmp_path: Path) -> None:
    from birkin.office.adapters.catalog import adapter_inventory, supported_formats
    from birkin.office.extract import SUPPORTED_FORMATS
    from birkin.tools import build_registry
    from birkin.tools._types import ToolContext
    from birkin.tools.documents import NAMES

    inventory = adapter_inventory()
    inventory_formats = tuple(item["format"] for item in inventory)
    assert supported_formats() == inventory_formats
    assert SUPPORTED_FORMATS == frozenset(supported_formats("extract"))

    registry = build_registry(
        ToolContext(cfg={"spill_threshold": 1_000_000}, client=None, cwd=tmp_path),
        include={"documents"},
    )
    assert tuple(registry.names()) == NAMES
    result = registry.execute("list_document_adapters", {})
    assert not result.is_error
    body = cast("dict[str, object]", json.loads(cast("str", result.content)))
    assert body["adapters"] == inventory
