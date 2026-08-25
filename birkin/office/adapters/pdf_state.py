"""Read-only PDF state inspection using the approved optional pypdf boundary."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..errors import DocumentError, DocumentErrorCode
from .pdf_capabilities import pdf_capabilities
from .pdf_inventory import field_count, images_on_page, inventory
from .pdf_types import ParsedPage, ParsedPdf, mapping, permission_validity

if TYPE_CHECKING:
    from pypdf import PdfReader

_INSTALL_HINT = "pip install 'birkin[office-advanced]'"
INSPECT_SAMPLE_PAGES = 5


@dataclass(frozen=True)
class PDFLimits:
    max_file_bytes: int = 100_000_000
    max_pages: int = 200
    max_text_bytes: int = 10_000_000
    max_images: int = 10_000


DEFAULT_PDF_LIMITS = PDFLimits()


def _limit(message: str, reason: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.LIMIT_EXCEEDED,
        "inspect",
        message,
        details={"reason": reason},
    )


def _reader(path: Path, password: str | bytes | None) -> PdfReader:
    try:
        from pypdf import PdfReader
        from pypdf.errors import WrongPasswordError
    except ImportError as exc:
        raise DocumentError(
            DocumentErrorCode.CAPABILITY_UNAVAILABLE,
            "inspect",
            "deep PDF inspection requires the approved pypdf package",
            details={
                "reason": "pdf_parser_unavailable",
                "package": "pypdf",
                "install_hint": _INSTALL_HINT,
            },
        ) from exc
    try:
        return PdfReader(os.fspath(path), strict=True, password=password)
    except WrongPasswordError as exc:
        raise DocumentError(
            DocumentErrorCode.PERMISSION_DENIED,
            "inspect",
            "the supplied PDF password is invalid",
            details={"reason": "pdf_invalid_password"},
        ) from exc
    except Exception as exc:
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID,
            "inspect",
            f"strict PDF parsing failed: {exc}",
            details={"reason": "pdf_structure_invalid"},
        ) from exc


def _locked_state() -> dict[str, object]:
    capabilities = pdf_capabilities(
        "unknown_encrypted", "unknown_encrypted", "pdf_password_required"
    )
    return {
        "encrypted": True,
        "credential_required": True,
        "security": {
            "encrypted": True,
            "credential_required": True,
            "credential_supplied": False,
            "permissions": "unknown",
        },
        "form_type": "unknown_encrypted",
        "forms": {
            "state": "unknown_encrypted",
            "has_acroform": None,
            "has_xfa": None,
            "field_count": None,
        },
        "content_type": "unknown_encrypted",
        "content": {
            "state": "unknown_encrypted",
            "native_text": None,
            "image_only": None,
            "pages": None,
            "image_pages": None,
        },
        "signed": None,
        "signatures": {
            "present": None,
            "count": None,
            "items": [],
            "cryptographic_verification": "unsupported",
            "trust_evaluation": "unsupported",
        },
        "active_content": [],
        "active_content_inspection": "credential_required",
        "capabilities": capabilities,
    }


def _basic_state(path: Path) -> tuple[dict[str, object], ParsedPdf]:
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-2048:]:
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID,
            "inspect",
            "PDF header or end marker is invalid",
            details={"reason": "pdf_structure_invalid"},
        )
    encrypted = b"/Encrypt" in raw
    capabilities = pdf_capabilities(
        "unknown",
        "backend_unavailable",
        "pdf_parser_unavailable",
    )
    state: dict[str, object] = {
        "encrypted": encrypted,
        "credential_required": False,
        "security": {
            "encrypted": encrypted,
            "credential_required": False,
            "credential_supplied": False,
            "permissions": None,
            "permissions_valid": None,
            "text_extraction_allowed": None,
        },
        "form_type": "unknown",
        "forms": {
            "state": "unknown",
            "has_acroform": None,
            "has_xfa": None,
            "field_count": None,
        },
        "content_type": "backend_unavailable",
        "content": {
            "state": "backend_unavailable",
            "native_text": None,
            "image_only": None,
            "pages": None,
            "image_pages": None,
        },
        "signed": None,
        "signatures": {
            "present": None,
            "count": None,
            "items": [],
            "cryptographic_verification": "unsupported",
            "trust_evaluation": "unsupported",
        },
        "active_content": [],
        "active_content_inspection": "parser_unavailable",
        "capabilities": capabilities,
    }
    return state, ParsedPdf(encrypted, None, (), None, None)


def inspect_pdf(
    path: Path,
    password: str | bytes | None = None,
    *,
    limits: PDFLimits = DEFAULT_PDF_LIMITS,
) -> tuple[dict[str, object], ParsedPdf]:
    source = path
    if source.stat().st_size > limits.max_file_bytes:
        raise _limit("PDF exceeds file byte limit", "pdf_file_bytes")
    try:
        reader = _reader(source, password)
    except DocumentError as exc:
        if exc.code is not DocumentErrorCode.CAPABILITY_UNAVAILABLE:
            raise
        return _basic_state(source)
    encrypted = bool(reader.is_encrypted)
    if encrypted and password is None:
        locked = ParsedPdf(True, None, (), None, None)
        return _locked_state(), locked

    if len(reader.pages) > limits.max_pages:
        raise _limit("PDF exceeds page limit", "pdf_pages")
    pages: list[ParsedPage] = []
    page_text: list[str] = []
    text_bytes = 0
    image_count = 0
    for page_index, raw_page in enumerate(reader.pages):
        page = ParsedPage.from_object(raw_page)
        if page_index >= INSPECT_SAMPLE_PAGES:
            pages.append(page)
            continue
        text = page.extract_text() or ""
        page = page.with_cached_text(text)
        pages.append(page)
        text_bytes += len(text.encode("utf-8"))
        if text_bytes > limits.max_text_bytes:
            raise _limit("PDF exceeds text byte limit", "pdf_text_bytes")
        page_text.append(text)
        image_count += images_on_page(page)
        if image_count > limits.max_images:
            raise _limit("PDF exceeds image count limit", "pdf_images")
    document = ParsedPdf(
        is_encrypted=encrypted,
        root_object=reader.root_object,
        pages=tuple(pages),
        user_access_permissions=reader.user_access_permissions,
        permissions_valid=permission_validity(reader),
    )
    root = mapping(document.root_object)
    if root is None:
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID,
            "inspect",
            "PDF catalog is not a dictionary",
            details={"reason": "pdf_structure_invalid"},
        )
    acroform = mapping(root.get("/AcroForm")) if "/AcroForm" in root else None
    has_acroform = acroform is not None
    has_xfa = bool(acroform is not None and "/XFA" in acroform)
    form_type = "xfa" if has_xfa else "acroform" if has_acroform else "flat_or_no_form"
    image_pages = image_count > 0
    native_text = any(text.strip() for text in page_text)
    content_type = (
        "native_text"
        if native_text
        else "image_only"
        if image_pages
        else "empty_or_vector"
    )
    signatures, active = inventory(document, source.stat().st_size)
    permissions = document.user_access_permissions
    permission_bits = permissions if isinstance(permissions, int) else None
    extraction_allowed = not encrypted or bool(
        permission_bits is not None and permission_bits & (16 | 512)
    )
    reason = "pdf_extraction_permission_denied" if not extraction_allowed else None
    capabilities = pdf_capabilities(form_type, content_type, reason)
    validity = document.permissions_valid
    return {
        "encrypted": encrypted,
        "credential_required": False,
        "security": {
            "encrypted": encrypted,
            "credential_required": False,
            "credential_supplied": password is not None,
            "permissions": permission_bits,
            "permissions_valid": (
                bool(validity) if encrypted and validity is not None else None
            ),
            "text_extraction_allowed": extraction_allowed,
        },
        "form_type": form_type,
        "forms": {
            "state": form_type,
            "has_acroform": has_acroform,
            "has_xfa": has_xfa,
            "field_count": field_count(acroform) if has_acroform else 0,
        },
        "content_type": content_type,
        "content": {
            "state": content_type,
            "native_text": native_text,
            "image_only": content_type == "image_only",
            "pages": len(document.pages),
            "image_pages": image_pages,
        },
        "signed": bool(signatures),
        "signatures": {
            "present": bool(signatures),
            "count": len(signatures),
            "items": signatures,
            "cryptographic_verification": "unsupported",
            "trust_evaluation": "unsupported",
        },
        "active_content": active,
        "active_content_inspection": "inventory_only_not_executed",
        "capabilities": capabilities,
    }, document
