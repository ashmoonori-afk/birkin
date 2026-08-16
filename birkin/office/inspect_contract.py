"""Bounded, JSON-safe document inspection contract assembly."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from .adapters.catalog import AdapterInventory
from .errors import DocumentError, DocumentErrorCode
from .package import PackageManifest, preflight_package
from .service_types import SourceIdentity

_MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
    "hwpx": "application/hwp+zip",
}
_REQUIRED_PART = {
    "docx": "word/document.xml",
    "xlsx": "xl/workbook.xml",
    "pptx": "ppt/presentation.xml",
}
_MAX_INVENTORY_ITEMS = 10_000


def source_identity(digest: str) -> SourceIdentity:
    return {"sha256": digest, "locator": f"sha256:{digest}"}


def _invalid(message: str) -> DocumentError:
    return DocumentError(DocumentErrorCode.PACKAGE_INVALID, "probe", message)


def verify_identity(path: Path, format_name: str) -> PackageManifest | None:
    """Bind a supported extension to signatures and required package parts."""
    if format_name not in _MEDIA_TYPES:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_FORMAT,
            "probe",
            f"unsupported format: {format_name}",
        )
    if format_name == "pdf":
        with path.open("rb") as source:
            header = source.read(8)
            _ = source.seek(max(0, path.stat().st_size - 1024))
            trailer = source.read()
        if not header.startswith(b"%PDF-") or b"%%EOF" not in trailer:
            raise _invalid(".pdf content does not have a valid PDF identity")
        return None
    manifest = preflight_package(path)
    parts = manifest["parts"]
    required = _REQUIRED_PART.get(format_name)
    if required is not None and required not in parts:
        raise _invalid(f".{format_name} package is missing required part: {required}")
    if format_name == "hwpx":
        mimetype_part = parts.get("mimetype")
        mimetype = None if mimetype_part is None else mimetype_part["bytes"]
        has_section = any(name.startswith("Contents/section") for name in parts)
        if mimetype != b"application/hwp+zip" or not has_section:
            raise _invalid(".hwpx content does not have a valid HWPX identity")
    return manifest


def _json_value(value: object) -> object:
    if isinstance(value, bytes):
        return 1
    if isinstance(value, list):
        all_values = cast("list[object]", value)
        values = all_values[:_MAX_INVENTORY_ITEMS]
        if values and all(isinstance(item, bytes) for item in values):
            return len(all_values)
        normalized = [_json_value(item) for item in values]
        if normalized and all(isinstance(item, str) for item in normalized):
            return sorted(cast("list[str]", normalized))
        return normalized
    if isinstance(value, Mapping):
        raw = cast("Mapping[object, object]", value)
        return {str(key): _json_value(raw[key]) for key in sorted(raw, key=str)}
    return value


def build_inspection(
    path: Path,
    format_name: str,
    digest: str,
    summary: Mapping[str, object],
    adapter: AdapterInventory,
    manifest: PackageManifest | None,
) -> dict[str, object]:
    active = [] if manifest is None else [dict(item) for item in manifest["active_content"]]
    external = [] if manifest is None else [dict(item) for item in manifest["external_relationships"]]
    findings: list[dict[str, object]] = [
        {"code": "ACTIVE_CONTENT", **item} for item in active
    ] + [{"code": "EXTERNAL_RELATIONSHIP", **item} for item in external]
    adapter_risks = summary.get("risks")
    if isinstance(adapter_risks, list):
        normalized_risks = _json_value(cast("list[object]", adapter_risks))
        if isinstance(normalized_risks, list):
            findings.extend(
                cast("list[dict[str, object]]", normalized_risks)
            )
    warnings = ["active content was inventoried but never executed"] if active else []
    return {
        "document_ir_artifact": None,
        "source": source_identity(digest),
        "format": format_name,
        "metadata": {
            "size_bytes": path.stat().st_size,
            "media_type": _MEDIA_TYPES[format_name],
            "package_parts": 0 if manifest is None else len(manifest["parts"]),
        },
        "structure": {"inventory": _json_value(summary)},
        "risks": {
            "active_content": active,
            "external_relationships": external,
            "findings": findings,
            "coverage": (
                "package relationships and known active parts"
                if manifest is not None
                else (
                    "PDF signature and parser-visible structure only"
                    if format_name == "pdf"
                    else "format-specific encrypted package metadata only"
                )
            ),
        },
        "adapter": adapter,
        "capabilities": adapter["capabilities"],
        "warnings": warnings,
    }
