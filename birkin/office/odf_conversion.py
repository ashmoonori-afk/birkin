"""Explicit LibreOffice-only ODF conversion boundary; no converter is emulated."""

from __future__ import annotations

import shutil
from pathlib import Path

from .odf_package import preflight_odf
from .odf_types import (
    OdfConversionReceipt,
    OdfConversionRefusal,
    OdfConversionRequest,
    OdfPreflight,
)

_APPROVED_ROUTES = {
    ("odt", "docx"): ("writer8", "Office Open XML Text"),
    ("odt", "pdf"): ("writer8", "writer_pdf_Export"),
    ("ods", "xlsx"): ("calc8", "Calc MS Excel 2007 XML"),
    ("ods", "pdf"): ("calc8", "calc_pdf_Export"),
    ("odp", "pptx"): ("impress8", "Impress MS PowerPoint 2007 XML"),
    ("odp", "pdf"): ("impress8", "impress_pdf_Export"),
}


def probe_libreoffice() -> Path | None:
    """Locate soffice without invoking it or opening untrusted input."""
    located = shutil.which("soffice")
    return None if located is None else Path(located)


def _receipt(
    preflight: OdfPreflight,
    request: OdfConversionRequest,
    code: str,
    reason: str,
) -> OdfConversionReceipt:
    return OdfConversionReceipt(
        status="converter_unavailable" if code in {"converter_unavailable", "isolated_runner_unavailable"} else "refused",
        reason_code=code,
        reason=reason,
        source_sha256=preflight.source_sha256,
        source_format=preflight.format,
        target_format=request.target_format,
        engine=request.engine,
        policy=request.policy,
        prospective_loss_categories=preflight.prospective_loss_categories,
    )


def _refuse(
    preflight: OdfPreflight,
    request: OdfConversionRequest,
    code: str,
    reason: str,
) -> None:
    raise OdfConversionRefusal(_receipt(preflight, request, code, reason))


def _validate_request(preflight: OdfPreflight, request: OdfConversionRequest) -> None:
    route = _APPROVED_ROUTES.get((preflight.format, request.target_format))
    if route is None:
        _refuse(preflight, request, "unsupported_target", "target format is not approved for this ODF input")
    if (request.engine.input_filter, request.engine.output_filter) != route:
        _refuse(preflight, request, "unapproved_filter", "LibreOffice input/output filters do not exactly match the approved route")
    if request.source_sha256 != preflight.source_sha256:
        _refuse(preflight, request, "source_hash_mismatch", "request source hash does not match the preflighted package")
    consent = request.consent
    if (
        consent.source_sha256 != preflight.source_sha256
        or consent.manifest_sha256 != preflight.manifest_sha256
        or consent.security_inventory_sha256 != preflight.security_inventory_sha256
    ):
        _refuse(preflight, request, "stale_manifest_security_consent", "manifest/security consent is not bound to this package inventory")
    accepted = set(request.loss_budget.accepted_categories)
    required = set(preflight.prospective_loss_categories)
    if not required.issubset(accepted):
        _refuse(preflight, request, "loss_budget_exceeded", f"loss budget omits categories: {sorted(required - accepted)}")


def convert_odf(source: Path, output: Path, request: OdfConversionRequest) -> OdfConversionReceipt:
    """Validate a conversion request, then report the unavailable safe boundary.

    Even if soffice exists, execution is unavailable until an offline jailed
    runner is implemented. This function never creates output or temporary files.
    """
    source_path, output_path = Path(source), Path(output)
    preflight = preflight_odf(source_path)
    _validate_request(preflight, request)
    if output_path.suffix.lower() != f".{request.target_format}":
        _refuse(preflight, request, "output_extension_mismatch", "output extension does not match target format")
    if output_path.exists() or output_path.is_symlink():
        _refuse(preflight, request, "output_exists", "conversion boundary never overwrites output")
    if preflight_odf(source_path).source_sha256 != preflight.source_sha256:
        _refuse(preflight, request, "source_changed", "source changed after ODF preflight")
    executable = probe_libreoffice()
    if executable is None:
        return _receipt(
            preflight,
            request,
            "converter_unavailable",
            f"pinned LibreOffice {request.engine.version} soffice executable is unavailable",
        )
    return _receipt(
        preflight,
        request,
        "isolated_runner_unavailable",
        f"{executable.name} was found, but the required offline jailed runner is unavailable",
    )


request_odf_conversion = convert_odf
