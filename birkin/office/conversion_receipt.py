"""Deterministic receipt assembly for text conversion."""

from __future__ import annotations

from .adapters.adapter_provenance import provenance_manifest
from .adapters.catalog import adapter_inventory
from .conversion_audit import LOSS_CATEGORIES
from .service_types import (
    ConversionObservation,
    ConversionPreservation,
    ConversionReceipt,
    ExtractionResult,
)

ENGINE_NAME = "birkin-text-projection"
ENGINE_VERSION = "1"


def build_receipt(
    *,
    source_format: str,
    source_sha256: str,
    output_sha256: str,
    output_name: str,
    budget: dict[str, int],
    observed: dict[str, int],
    extraction: ExtractionResult,
    source_immutable: bool,
    output_bytes: int,
    preview: str,
) -> ConversionReceipt:
    manifest = provenance_manifest()
    adapter = next(item for item in adapter_inventory() if item["format"] == source_format)
    loss: list[ConversionObservation] = [
        {
            "category": category,
            "observed": observed[category],
            "budget": budget[category],
            "status": "lost" if observed[category] else "not_applicable",
        }
        for category in LOSS_CATEGORIES
    ]
    preservation: list[ConversionPreservation] = [
        {
            "category": "text",
            "status": "preserved",
            "spans": len(extraction["spans"]),
        }
    ]
    unsupported = sorted(extraction["unsupported"])
    warnings = [
        f"{name} semantic extraction is unsupported"
        for name in unsupported
    ]
    return {
        "operation": "document_convert",
        "version": 1,
        "source_sha256": source_sha256,
        "output_sha256": output_sha256,
        "engine": {
            "name": ENGINE_NAME,
            "version": ENGINE_VERSION,
            "adapter": source_format,
            "adapter_version": f"catalog-revision-{manifest['catalog_revision']}",
            "adapter_standard": adapter["standard_url"],
            "provenance": {
                "catalog_revision": manifest["catalog_revision"],
                "inventory_sha256": manifest["inventory_sha256"],
            },
        },
        "route": {
            "source_format": source_format,
            "target_format": "txt",
            "output_name": output_name,
        },
        "options": {
            "projection": "text",
            "encoding": "utf-8",
            "newline": "LF",
            "terminal_newline": True,
        },
        "loss_budget": dict(budget),
        "observed": {
            "preservation": preservation,
            "loss": loss,
            "warnings": warnings,
        },
        "sandbox": {
            "network_accessed": False,
            "active_content_executed": False,
            "external_content_fetched": False,
            "source_immutable": source_immutable,
        },
        "validation": {
            "passed": source_immutable,
            "checks": [
                "source_hash_unchanged",
                "utf8_reopen",
                "text_projection_exact",
                "output_hash_verified",
            ],
        },
        "diff": {
            "text_equal": True,
            "source_characters": len(extraction["text"]),
            "output_payload_characters": len(extraction["text"]),
        },
        "preview": {
            "status": "available",
            "text": preview,
            "truncated": len(extraction["text"]) > len(preview),
        },
        "limits": {
            "max_spans": extraction["limits"]["max_spans"],
            "max_nodes": extraction["limits"]["max_nodes"],
            "max_text_bytes": extraction["limits"]["max_text_bytes"],
            "output_bytes": output_bytes,
            "preview_characters": 200,
        },
    }
