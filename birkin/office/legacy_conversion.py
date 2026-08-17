"""Explicit conversion boundary; no converter is bundled or emulated."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .legacy_preflight import preflight_legacy
from .legacy_types import (
    LegacyConversionRequest,
    LegacyLimits,
    LegacyPreflight,
    LegacyReceipt,
    LegacyRefusal,
)

_TARGETS: dict[str, frozenset[str]] = {
    "doc": frozenset(("docx", "odt", "pdf", "txt")),
    "xls": frozenset(("xlsx", "ods", "pdf", "csv")),
    "ppt": frozenset(("pptx", "odp", "pdf")),
    "rtf": frozenset(("docx", "odt", "pdf", "txt")),
}


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _receipt(
    preflight: LegacyPreflight,
    request: LegacyConversionRequest,
    code: str,
    reason: str,
    *,
    status: str = "refused",
) -> LegacyReceipt:
    if status == "converter_unavailable":
        typed_status = "converter_unavailable"
    else:
        typed_status = "refused"
    return LegacyReceipt(
        status=typed_status,
        source_sha256=preflight.source_sha256,
        source_format=preflight.format,
        target_format=request.target_format,
        prospective_loss_categories=preflight.prospective_loss_categories,
        reason_code=code,
        reason=reason,
        engine=request.engine,
        policy=request.policy,
    )


def probe_legacy_converter(request: LegacyConversionRequest) -> Path | None:
    """Report that external conversion engines are permanently unsupported."""
    _ = request
    return None


def convert_legacy(
    source: Path,
    output: Path,
    request: LegacyConversionRequest,
    *,
    limits: LegacyLimits | None = None,
) -> LegacyReceipt:
    """Preflight an explicit request and return a refusal/unavailable receipt.

    This package deliberately has no in-process legacy writer and no process
    sandbox implementation. A converter is never run unless that isolation
    boundary exists; currently even an installed executable is refused.
    """
    source_path = Path(source)
    output_path = Path(output)
    preflight = preflight_legacy(source_path, limits)
    target = request.target_format.lower()
    if request.target_format != target or target not in _TARGETS[preflight.format]:
        raise LegacyRefusal(
            _receipt(preflight, request, "unsupported_target", "target format is not approved for this legacy input")
        )
    if output_path.suffix.lower() != f".{target}":
        raise LegacyRefusal(
            _receipt(preflight, request, "output_extension_mismatch", "output extension does not match target format")
        )
    if output_path.exists():
        raise LegacyRefusal(
            _receipt(preflight, request, "output_exists", "conversion boundary never overwrites an output")
        )
    if _hash(source_path) != preflight.source_sha256:
        raise LegacyRefusal(
            _receipt(preflight, request, "source_changed", "source changed after legacy preflight")
        )
    return _receipt(
        preflight,
        request,
        "external_engine_forbidden",
        "external application conversion engines are not a shipped capability",
    )


request_legacy_conversion = convert_legacy
