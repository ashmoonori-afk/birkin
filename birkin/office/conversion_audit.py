"""Deterministic source-feature inventory for bounded text conversion."""

from __future__ import annotations

import re
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from .conversion_schema import LOSS_CATEGORIES
from .errors import DocumentError, DocumentErrorCode
from .package import preflight_package

def normalize_budget(value: Mapping[str, object] | None) -> dict[str, int]:
    """Return a complete budget; omitted categories require zero loss."""
    if value is None:
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "plan",
            "text conversion requires an explicit loss_budget",
            details={"categories": list(LOSS_CATEGORIES)},
        )
    unknown = sorted(set(value) - set(LOSS_CATEGORIES))
    if unknown:
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "plan",
            "loss_budget contains unknown categories",
            details={"unknown": unknown, "categories": list(LOSS_CATEGORIES)},
        )
    budget: dict[str, int] = {}
    for category in LOSS_CATEGORIES:
        raw = value.get(category, 0)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "plan",
                f"loss_budget.{category} must be a non-negative integer",
            )
        budget[category] = raw
    return budget


def _count(parts: Mapping[str, bytes], patterns: tuple[bytes, ...]) -> int:
    return sum(len(re.findall(pattern, data, re.IGNORECASE)) for data in parts.values() for pattern in patterns)


def _zip_observations(path: Path) -> tuple[dict[str, int], list[dict[str, str]]]:
    try:
        with zipfile.ZipFile(path) as archive:
            encrypted = sum(bool(item.flag_bits & 1) for item in archive.infolist())
    except (OSError, zipfile.BadZipFile) as exc:
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "probe", "invalid conversion source package") from exc
    if encrypted:
        return {category: 0 for category in LOSS_CATEGORIES} | {"signature_encryption": encrypted}, []
    manifest = preflight_package(path)
    parts = {name: item["bytes"] for name, item in manifest["parts"].items()}
    names = tuple(parts)
    active = [dict(item) for item in manifest["active_content"]]
    signature = sum(
        "_xmlsignatures/" in name.lower()
        or "digitalsignature" in name.lower()
        or name.lower().endswith("origin.sigs")
        for name in names
    )
    table_markers = _count(parts, (rb"<(?:w:tbl|table|hp:tbl)\b",))
    structure = max(1, table_markers)
    style_parts = sum(
        any(token in name.lower() for token in ("styles", "theme", "layout", "master"))
        for name in names
    )
    formulas = _count(parts, (rb"<(?:[a-z]+:)?f(?:\s|>)", rb"<formula\b"))
    charts_media = sum(
        any(token in f"/{name.lower()}" for token in ("/charts/", "/media/", "/drawings/"))
        for name in names
    )
    revisions = _count(parts, (rb"<w:(?:ins|del|moveFrom|moveTo)\b", rb"commentRange"))
    revisions += sum("comments" in name.lower() for name in names)
    fields = _count(parts, (rb"<w:(?:fldSimple|fldChar|sdt)\b", rb"<hp:field\b", rb"<form\b"))
    metadata = sum(
        name.lower().startswith("docprops/")
        or "metadata" in name.lower()
        or name.lower().endswith("manifest.xml")
        for name in names
    )
    accessibility = _count(parts, (rb"\b(?:descr|alt|title)\s*=", rb"<[^>]*accessibility"))
    observations = {
        "structure": structure,
        "style_layout": max(1, style_parts),
        "formula_cache": formulas,
        "chart_media": charts_media,
        "macro_active_content": len(active),
        "tracked_changes_comments": revisions,
        "form_field": fields,
        "metadata": metadata,
        "signature_encryption": signature,
        "accessibility": accessibility,
    }
    return observations, cast("list[dict[str, str]]", active)


def _pdf_observations(path: Path) -> tuple[dict[str, int], list[dict[str, str]]]:
    raw = path.read_bytes()
    encrypted = len(re.findall(rb"/Encrypt\b", raw))
    signatures = len(re.findall(rb"/Type\s*/Sig\b|/ByteRange\s*\[", raw))
    active_count = len(re.findall(rb"/(?:JavaScript|JS|Launch|OpenAction)\b", raw))
    return {
        "structure": max(1, len(re.findall(rb"/Type\s*/Page\b", raw))),
        "style_layout": 1,
        "formula_cache": 0,
        "chart_media": len(re.findall(rb"/Subtype\s*/Image\b", raw)),
        "macro_active_content": active_count,
        "tracked_changes_comments": len(re.findall(rb"/Subtype\s*/(?:Text|Highlight|StrikeOut)\b", raw)),
        "form_field": len(re.findall(rb"/AcroForm\b|/FT\s*/", raw)),
        "metadata": len(re.findall(rb"/(?:Info|Metadata)\b", raw)),
        "signature_encryption": encrypted + signatures,
        "accessibility": len(re.findall(rb"/(?:StructTreeRoot|MarkInfo|Alt)\b", raw)),
    }, ([{"part_uri": "pdf", "kind": "active_action"}] if active_count else [])


def audit_source(path: Path, format_name: str) -> tuple[dict[str, int], list[dict[str, str]]]:
    if format_name == "pdf":
        return _pdf_observations(path)
    return _zip_observations(path)
