"""Layered, truthful validation receipts for supported document artifacts."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
from pathlib import Path
from typing import Literal, TypedDict

from .adapters.catalog import supported_formats
from .errors import DocumentError
from .package import PackageManifest, preflight_package
from .package_types import DEFAULT_LIMITS

ValidationStatus = Literal["pass", "fail", "warning", "unsupported", "not-run"]


class ValidationFinding(TypedDict):
    code: str
    severity: str
    message: str
    location: str | None


class ValidationCheck(TypedDict):
    name: str
    status: ValidationStatus
    passed: bool
    validator: str
    version: str
    scope: str
    limits: dict[str, object]
    findings: list[ValidationFinding]


class ValidationResult(TypedDict):
    operation: Literal["document_validate"]
    version: int
    valid: bool
    complete: bool
    status: ValidationStatus
    format: str
    source_sha256: str
    checks: list[ValidationCheck]
    layers: dict[str, ValidationCheck]
    warnings: list[str]
    external_relationships: list[dict[str, object]]
    active_content: list[dict[str, object]]


_SUPPORTED = frozenset(supported_formats("validate"))
_REQUIRED = {
    "docx": "word/document.xml",
    "xlsx": "xl/workbook.xml",
    "pptx": "ppt/presentation.xml",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finding(code: str, severity: str, message: str, location: str | None = None) -> ValidationFinding:
    return {"code": code, "severity": severity, "message": message, "location": location}


def _layer(
    name: str,
    status: ValidationStatus,
    validator: str,
    scope: str,
    findings: list[ValidationFinding] | None = None,
    *,
    version: str = "1",
    limits: dict[str, object] | None = None,
) -> ValidationCheck:
    return {
        "name": name,
        "status": status,
        "passed": status in {"pass", "warning"},
        "validator": validator,
        "version": version,
        "scope": scope,
        "limits": limits or {},
        "findings": findings or [],
    }


def _package_limits() -> dict[str, object]:
    return {
        "max_entries": DEFAULT_LIMITS.max_entries,
        "max_uncompressed_bytes": DEFAULT_LIMITS.max_uncompressed_bytes,
        "max_entry_ratio": DEFAULT_LIMITS.max_entry_ratio,
        "max_xml_bytes": DEFAULT_LIMITS.max_xml_bytes,
        "max_xml_nodes": DEFAULT_LIMITS.max_xml_nodes,
        "max_xml_depth": DEFAULT_LIMITS.max_xml_depth,
    }


def _package_layer(path: Path, format_name: str) -> tuple[ValidationCheck, PackageManifest | None]:
    if format_name == "pdf":
        with path.open("rb") as source:
            header = source.read(8)
            _ = source.seek(max(path.stat().st_size - 1024, 0))
            trailer = source.read()
        ok = header.startswith(b"%PDF-") and b"%%EOF" in trailer
        findings = [] if ok else [_finding("PDF_IDENTITY", "error", "PDF header or EOF marker is invalid")]
        return _layer("package", "pass" if ok else "fail", "birkin-pdf-identity", "PDF signature and EOF marker", findings), None
    try:
        manifest = preflight_package(path)
    except DocumentError as exc:
        finding = _finding(exc.code.value, "error", exc.message)
        return _layer("package", "fail", "birkin-package-preflight", "ZIP metadata, paths, XML safety, and relationships", [finding], limits=_package_limits()), None
    return _layer("package", "pass", "birkin-package-preflight", "ZIP metadata, paths, XML safety, and relationships", limits=_package_limits()), manifest


def _schema_layer(format_name: str, manifest: PackageManifest | None, package_ok: bool) -> ValidationCheck:
    if not package_ok:
        return _layer("schema", "not-run", "none", "format identity and required roots", [_finding("PACKAGE_FAILED", "info", "schema probes were not run because package validation failed")])
    if format_name == "pdf":
        return _layer("schema", "unsupported", "none", "ISO 32000 schema/conformance", [_finding("NO_PDF_CONFORMANCE_ENGINE", "info", "no approved PDF conformance validator is registered")])
    if manifest is None:
        return _layer("schema", "not-run", "none", "format identity and required roots", [_finding("PACKAGE_UNAVAILABLE", "info", "schema probes require a valid package")])
    parts = manifest["parts"]
    missing: list[str] = []
    required = _REQUIRED.get(format_name)
    if required is not None and required not in parts:
        missing.append(required)
    if format_name == "hwpx":
        mimetype = parts.get("mimetype")
        if mimetype is None or mimetype["bytes"] != b"application/hwp+zip":
            missing.append("mimetype=application/hwp+zip")
        if not any(name.startswith("Contents/section") for name in parts):
            missing.append("Contents/section*.xml")
    findings = [_finding("REQUIRED_PART_MISSING", "error", f"required format root is missing: {part}", part) for part in missing]
    if findings:
        return _layer("schema", "fail", "birkin-format-root-probe", "required format roots only; not full standards conformance", findings)
    return _layer("schema", "warning", "birkin-format-root-probe", "required format roots only; not full standards conformance", [_finding("PARTIAL_SCHEMA_COVERAGE", "warning", "full standards schema validation is unavailable")])


def _formula_layer(format_name: str, manifest: PackageManifest | None) -> ValidationCheck:
    if format_name != "xlsx":
        return _layer("formula", "unsupported", "none", "spreadsheet formula recalculation", [_finding("NOT_A_SPREADSHEET", "info", "formula validation applies only to XLSX")])
    if manifest is None:
        return _layer("formula", "not-run", "none", "stored formulas and recalculated values", [_finding("PACKAGE_UNAVAILABLE", "info", "formula inventory requires a valid package")])
    formula_parts = sorted(name for name, part in manifest["parts"].items() if name.startswith("xl/worksheets/") and b"<f" in part["bytes"])
    detail = "no formula engine is registered; stored formulas were not recalculated"
    return _layer("formula", "not-run", "none", "stored formulas and recalculated values", [_finding("FORMULA_ENGINE_UNAVAILABLE", "info", detail, ",".join(formula_parts) or None)], limits={"inventoried_parts": len(formula_parts)})


def _openability_layer(path: Path, format_name: str, package_ok: bool) -> ValidationCheck:
    if not package_ok:
        return _layer("openability", "not-run", "none", "independent application reopen", [_finding("PACKAGE_FAILED", "info", "openability was not attempted")])
    if format_name != "pdf":
        return _layer("openability", "not-run", "none", "independent Office application reopen", [_finding("OFFICE_ENGINE_UNAVAILABLE", "info", "no approved pinned Office application engine is registered")])
    try:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
    except ImportError:
        return _layer("openability", "unsupported", "none", "strict PDF parser reopen", [_finding("PYPDF_UNAVAILABLE", "info", "approved optional pypdf parser is not installed")])
    try:
        _ = PdfReader(os.fspath(path), strict=True)
    except (OSError, ValueError, PyPdfError) as exc:
        return _layer("openability", "fail", "pypdf", "strict PDF parser reopen", [_finding("PYPDF_REJECTED", "error", str(exc)[:500])])
    version = importlib.metadata.version("pypdf")
    return _layer("openability", "pass", "pypdf", "strict PDF parser reopen", version=version)


def _security_layer(manifest: PackageManifest | None, format_name: str, package_ok: bool) -> ValidationCheck:
    if not package_ok:
        return _layer("security", "not-run", "none", "active content and external relationships", [_finding("PACKAGE_FAILED", "info", "security inventory was not completed")])
    if format_name == "pdf":
        return _layer("security", "warning", "birkin-pdf-identity", "signature bytes only", [_finding("PARTIAL_SECURITY_COVERAGE", "warning", "PDF active content and signature trust are not fully evaluated")])
    if manifest is None:
        return _layer("security", "not-run", "none", "active content and external relationships", [_finding("PACKAGE_UNAVAILABLE", "info", "security inventory requires a valid package")])
    findings = [_finding("EXTERNAL_RELATIONSHIP", "warning", item["target"], item["part_uri"]) for item in manifest["external_relationships"]]
    findings.extend(_finding("ACTIVE_CONTENT", "warning", item["kind"], item["part_uri"]) for item in manifest["active_content"])
    return _layer("security", "warning" if findings else "pass", "birkin-package-preflight", "known active parts and external relationships", findings, limits=_package_limits())


def validate_document(path: Path, format_name: str) -> ValidationResult:
    """Return all validation layers, including work that could not be performed."""
    if format_name not in _SUPPORTED:
        from .errors import DocumentErrorCode
        raise DocumentError(DocumentErrorCode.UNSUPPORTED_FORMAT, "validate", f"unsupported format: {format_name}")
    digest = _sha256(path)
    package, manifest = _package_layer(path, format_name)
    package_ok = package["status"] == "pass"
    layers = [
        _schema_layer(format_name, manifest, package_ok), package,
        _formula_layer(format_name, manifest), _openability_layer(path, format_name, package_ok),
        _security_layer(manifest, format_name, package_ok),
        _layer("fidelity", "not-run", "none", "rendered layout fidelity", [_finding("RENDERER_UNAVAILABLE", "info", "no approved pinned renderer is registered")]),
    ]
    statuses = [item["status"] for item in layers]
    status: ValidationStatus = "fail" if "fail" in statuses else ("pass" if all(item == "pass" for item in statuses) else "warning")
    external = [] if manifest is None else [dict(item) for item in manifest["external_relationships"]]
    active = [] if manifest is None else [dict(item) for item in manifest["active_content"]]
    warnings = [finding["message"] for item in layers for finding in item["findings"] if finding["severity"] in {"warning", "info"}]
    return {
        "operation": "document_validate", "version": 1, "valid": "fail" not in statuses,
        "complete": all(item == "pass" for item in statuses), "status": status,
        "format": format_name, "source_sha256": digest, "checks": layers,
        "layers": {item["name"]: item for item in layers}, "warnings": warnings,
        "external_relationships": external, "active_content": active,
    }
