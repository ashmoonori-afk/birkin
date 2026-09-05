"""Truthful bounded semantic preview contract for documents without a renderer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .adapters.catalog import adapter_inventory
from .errors import DocumentError, DocumentErrorCode
from .extract import extract_items
from .extract_contract import build_extraction
from .extract_package import extract_xlsx_cell_items

MAX_PREVIEW_SPANS = 100
MAX_PREVIEW_NODES = 100
MAX_PREVIEW_TEXT_BYTES = 20_000


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
) -> dict[str, object]:
    """Return semantic preview data or refuse visual artifact claims."""
    inventory = next(item for item in adapter_inventory() if item["format"] == format_name)
    provenance = _provenance(format_name, dict(inventory["capabilities"]["render"]))
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
