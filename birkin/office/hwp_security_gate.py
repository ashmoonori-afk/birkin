"""Truthful identity and security capability gate for binary HWP documents."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import cast

from .hwp_cfb import HwpCfb, HwpCfbError
from .hwp_policy import (
    INSPECTOR_PROVENANCE,
    OPERATIONS,
    capabilities,
    flag_evidence,
    unsupported_reasons,
)
from .hwp_types import HwpLimits, HwpRefusal, HwpRequiredTool

_SIGNATURE = b"HWP Document File".ljust(32, b"\0")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _refuse(digest: str, code: str, reason: str) -> HwpRefusal:
    return HwpRefusal(
        operation="inspect",
        source_sha256=digest,
        reason_code=code,
        reason=reason,
    )


def _header_and_inventory(
    data: bytes, limits: HwpLimits, digest: str
) -> tuple[HwpCfb, bytes]:
    try:
        cfb = HwpCfb(data, limits)
        file_header = cfb.entry("FileHeader")
        doc_info = cfb.entry("DocInfo")
        if file_header is None or doc_info is None:
            raise _refuse(
                digest,
                "hwp_required_stream_missing",
                "HWP requires FileHeader and DocInfo streams",
            )
        if doc_info.entry_type != 2:
            raise _refuse(
                digest, "hwp_required_stream_invalid", "HWP DocInfo must be a stream"
            )
        header = cfb.read_stream(file_header, max_bytes=limits.max_file_header_bytes)
    except HwpRefusal:
        raise
    except HwpCfbError as error:
        raise _refuse(digest, error.code, str(error)) from error
    if len(header) != 256:
        raise _refuse(
            digest,
            "hwp_fileheader_size_invalid",
            "HWP FileHeader must be exactly 256 bytes",
        )
    if header[:32] != _SIGNATURE:
        raise _refuse(
            digest,
            "hwp_fileheader_signature_invalid",
            "HWP FileHeader signature is invalid",
        )
    return cfb, header


def _validate_layout(cfb: HwpCfb, flags: int, digest: str) -> None:
    distribution = bool(flags & (1 << 2))
    body_text = cfb.entry("BodyText")
    view_text = cfb.entry("ViewText")
    if distribution and (view_text is None or body_text is not None):
        raise _refuse(
            digest,
            "hwp_distribution_layout_invalid",
            "distribution HWP requires ViewText storage and must not expose BodyText storage",
        )
    if not distribution and (body_text is None or view_text is not None):
        raise _refuse(
            digest,
            "hwp_body_layout_invalid",
            "non-distribution HWP requires BodyText storage and no ViewText storage",
        )
    selected = view_text if distribution else body_text
    if selected is None or selected.entry_type != 1:
        raise _refuse(
            digest,
            "hwp_body_layout_invalid",
            "HWP body container must be a CFB storage",
        )
    if not any(
        item.entry_type == 2 and re.fullmatch(r"Section\d+", item.name)
        for item in cfb.entries
    ):
        raise _refuse(
            digest,
            "hwp_section_stream_missing",
            "HWP body storage has no Section stream",
        )


def inspect_hwp_security(
    path: Path, limits: HwpLimits | None = None
) -> dict[str, object]:
    """Validate binary HWP identity and inventory only bounded header evidence."""
    source = Path(path)
    effective = limits or HwpLimits()
    size = source.stat().st_size
    if source.suffix.casefold() != ".hwp":
        raise _refuse(
            _hash(source),
            "hwp_extension_mismatch",
            "binary HWP content requires an exact .hwp extension",
        )
    if size > effective.max_input_bytes:
        raise _refuse(
            _hash(source),
            "hwp_input_limit",
            "HWP input exceeds the configured byte limit",
        )
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    size = len(data)
    cfb, header = _header_and_inventory(data, effective, digest)
    version_parts = tuple(reversed(header[32:36]))
    if not version_parts or version_parts[0] != 5:
        raise _refuse(
            digest,
            "hwp_version_unsupported",
            "only binary HWP 5.x FileHeader identity is accepted",
        )
    flags = int.from_bytes(header[36:40], "little")
    _validate_layout(cfb, flags, digest)
    present, evidence = flag_evidence(flags)
    password = bool(flags & (1 << 1))
    distribution = bool(flags & (1 << 2))
    certificate_encrypted = bool(flags & (1 << 8))
    return {
        "status": "accepted",
        "format": "hwp",
        "container": "cfb",
        "source": str(source),
        "source_sha256": digest,
        "size_bytes": size,
        "version": ".".join(str(part) for part in version_parts),
        "directory_inventory": [entry.name for entry in cfb.entries],
        "flag_evidence": evidence,
        "compressed": bool(flags & 1),
        "distribution_document": distribution,
        "password_protected": password,
        "certificate_encrypted": certificate_encrypted,
        "encrypted": password or certificate_encrypted,
        "drm_protected": bool(flags & ((1 << 4) | (1 << 10))),
        "signature_markers_present": bool(flags & ((1 << 7) | (1 << 9))),
        "signature_verification": "unsupported",
        "unsupported_reasons": unsupported_reasons(flags),
        "tool_provenance": INSPECTOR_PROVENANCE.copy(),
        "capabilities": capabilities(flags, present),
    }


def require_hwp_capability(path: Path, operation: str) -> dict[str, object]:
    """Return an available capability or raise its hash-bound refusal receipt."""
    if operation not in OPERATIONS:
        raise ValueError(f"unknown binary HWP operation: {operation}")
    report = inspect_hwp_security(path)
    available = cast("dict[str, dict[str, object]]", report["capabilities"])[operation]
    if available["state"] != "available":
        raw_tool = cast("dict[str, object]", available["required_tool"])
        raise HwpRefusal(
            operation=operation,
            source_sha256=cast("str", report["source_sha256"]),
            reason_code=cast("str", available["reason_code"]),
            reason=cast("str", available["reason"]),
            required_tool=HwpRequiredTool(name=cast("str", raw_tool["name"])),
        )
    return available
