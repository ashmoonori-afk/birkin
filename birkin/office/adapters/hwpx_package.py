"""Strict HWPX identity and hash-bound package loading."""

from __future__ import annotations

from pathlib import Path

from ..errors import DocumentError, DocumentErrorCode
from ..package import preflight_package
from ..package_types import PackageManifest
from .hwpx_container import has_encryption_declaration, preflight_encrypted_hwpx
from .hwpx_encryption import inspect_encryption
from .hwpx_model import section_names

_OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")


def load_hwpx(
    source: Path,
    expected_source_sha256: str | None = None,
    *,
    allow_encryption_inventory: bool = False,
) -> tuple[dict[str, bytes], str, PackageManifest]:
    try:
        with source.open("rb") as stream:
            prefix = stream.read(8)
    except OSError:
        prefix = b""
    if source.suffix.lower() == ".hwp" or prefix == _OLE_MAGIC:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_FORMAT,
            "probe",
            "legacy binary HWP is unsupported and is not HWPX",
        )
    manifest = (
        preflight_encrypted_hwpx(source)
        if has_encryption_declaration(source)
        else preflight_package(source)
    )
    parts = {name: metadata["bytes"] for name, metadata in manifest["parts"].items()}
    if parts.get("mimetype") != b"application/hwp+zip" or not section_names(parts):
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_FORMAT,
            "probe",
            "artifact does not have a valid HWPX package identity",
        )
    digest = manifest["source_sha256"]
    if expected_source_sha256 is not None and digest != expected_source_sha256:
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "locate",
            "source hash does not match HWPX operation precondition",
            artifact_sha256=digest,
        )
    encryption = inspect_encryption(manifest)
    if encryption["encrypted"] and not allow_encryption_inventory:
        credential_required = encryption["password_required"]
        raise DocumentError(
            DocumentErrorCode.CAPABILITY_UNAVAILABLE,
            "decrypt",
            "encrypted HWPX content requires an approved decryptor and exact credential flow; neither is registered",
            artifact_sha256=digest,
            details={
                "reason": "unsupported_encryption_state",
                "password_required": credential_required,
                "credential_state": "required_not_supplied",
                "declaration_state": encryption["encryption_declaration_state"],
            },
        )
    return parts, digest, manifest


def require_hwpx_content(source: Path) -> None:
    """Refuse declared encryption before any content-consuming operation."""
    _ = load_hwpx(source)
