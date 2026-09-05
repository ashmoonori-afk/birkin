"""Bounded semantic previews and approved PDF page rendering."""

from __future__ import annotations

import hashlib
import json
import importlib.metadata
from pathlib import Path

from .adapters.catalog import adapter_inventory
from .errors import DocumentError, DocumentErrorCode
from .extract import extract_items
from .extract_contract import build_extraction
from .extract_package import extract_xlsx_cell_items

MAX_PREVIEW_SPANS = 100
MAX_PREVIEW_NODES = 100
MAX_PREVIEW_TEXT_BYTES = 20_000
MAX_RENDER_PAGES = 200


def _pdf_fonts(path: Path, page_index: int) -> list[str]:
    from pypdf import PdfReader

    page = PdfReader(Path(str(path)), strict=True).pages[page_index]
    fonts = page["/Resources"].get("/Font", {})
    return sorted({
        str(font.get_object().get("/BaseFont", "unknown"))
        for font in fonts.values()
    })


def _render_pdf(path: Path, target: Path, output_format: str, page: int | None) -> dict[str, object]:
    import pypdfium2
    from PIL import Image, ImageChops

    document = pypdfium2.PdfDocument(Path(str(path)))
    try:
        page_count = len(document)
        wanted = 1 if page is None else page
        if page_count > MAX_RENDER_PAGES or wanted < 1 or wanted > page_count:
            raise DocumentError(
                DocumentErrorCode.LIMIT_EXCEEDED,
                "render",
                "PDF page is outside the bounded render range",
                details={"page": wanted, "page_count": page_count, "maximum_pages": MAX_RENDER_PAGES},
            )
        scale = 1.5 if output_format == "png" else 0.5
        pdf_page = document[wanted - 1]
        try:
            bitmap = pdf_page.render(scale=scale)
            try:
                image = bitmap.to_pil().convert("RGB")
                bounds = ImageChops.difference(
                    image, Image.new("RGB", image.size, "white")
                ).getbbox()
                image.save(target, format="PNG")
            finally:
                bitmap.close()
        finally:
            pdf_page.close()
    finally:
        document.close()
    return {
        "page": wanted,
        "page_count": page_count,
        "settings": {"scale": scale, "pixel_format": "RGBA", "output_format": "png"},
        "fonts": _pdf_fonts(path, wanted - 1),
        "quality_checks": {
            "blank_page": bounds is None,
            "content_bounds": None if bounds is None else list(bounds),
            "edge_contact": False if bounds is None else (
                bounds[0] == 0 or bounds[1] == 0 or bounds[2] == image.width or bounds[3] == image.height
            ),
        },
    }


def _provenance(format_name: str, capability: dict[str, object]) -> dict[str, object]:
    return {
        "registry": "office adapter catalog",
        "format": format_name,
        "capability": capability,
        "requirements": [
            "approved package",
            "pinned version",
            "renderer identity",
            "deterministic settings",
        ],
    }


def render_document(
    path: Path,
    format_name: str,
    source_sha256: str,
    *,
    output_format: str,
    page: int | None,
    output_path: Path | None = None,
) -> dict[str, object]:
    """Return semantic preview data or refuse visual artifact claims."""
    inventory = next(item for item in adapter_inventory() if item["format"] == format_name)
    provenance = _provenance(format_name, dict(inventory["capabilities"]["render"]))
    if format_name == "pdf" and output_format in {"png", "thumbnail"}:
        if output_path is None:
            raise DocumentError(DocumentErrorCode.INTERNAL_ERROR, "render", "visual output path is required")
        rendered = _render_pdf(path, output_path, output_format, page)
        request = {"source_sha256": source_sha256, "output_format": output_format, **rendered["settings"], "page": rendered["page"]}
        request_sha256 = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "operation": "document_render",
            "version": 1,
            "status": "rendered",
            "render_kind": "page_image",
            "evidence_class": "visual_render",
            "visual_proof": True,
            "source": {"sha256": source_sha256, "locator": str(path)},
            "format": format_name,
            **rendered,
            "renderer": {"used": True, "name": "pypdfium2", "version": importlib.metadata.version("pypdfium2")},
            "receipt": {"operation": "document_render", "version": 1, "request_sha256": request_sha256, "source_sha256": source_sha256, "output_artifact": None},
        }
    if output_format != "structured_preview":
        if output_format not in {"pdf", "png", "thumbnail"}:
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "render",
                "output_format must be structured_preview, pdf, png, or thumbnail",
            )
        raise DocumentError(
            DocumentErrorCode.RENDER_UNAVAILABLE,
            "render",
            f"{output_format} rendering is unavailable: no approved pinned renderer is registered",
            artifact_sha256=source_sha256,
            details={
                "requested_output_format": output_format,
                "required_engine_provenance": provenance,
            },
        )
    extraction = build_extraction(
        extract_xlsx_cell_items(path) if format_name == "xlsx" else extract_items(path, format_name),
        format_name,
        source_sha256,
        projection="text",
        max_spans=MAX_PREVIEW_SPANS,
        max_nodes=MAX_PREVIEW_NODES,
        max_text_bytes=MAX_PREVIEW_TEXT_BYTES,
    )
    request = {
        "source_sha256": source_sha256,
        "output_format": output_format,
        "page": page,
        "limits": extraction["limits"],
    }
    request_sha256 = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "operation": "document_render",
        "version": 1,
        "status": "preview",
        "render_kind": "structured_preview",
        "evidence_class": "semantic_preview",
        "visual_proof": False,
        "source": extraction["source"],
        "format": format_name,
        "page": page,
        "preview": extraction,
        "renderer": {
            "used": False,
            "reason": "bounded extraction is not a visual renderer",
            "required_engine_provenance": provenance,
        },
        "receipt": {
            "operation": "document_render",
            "version": 1,
            "request_sha256": request_sha256,
            "source_sha256": source_sha256,
            "output_artifact": None,
        },
    }
