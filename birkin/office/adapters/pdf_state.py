"""Read-only PDF state inspection using the approved optional pypdf boundary."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from ..errors import DocumentError, DocumentErrorCode
from .pdf_capabilities import pdf_capabilities
from .pdf_inventory import field_count, images_on_page, inventory
from .pdf_types import ParsedPage, ParsedPdf, mapping, permission_validity

if TYPE_CHECKING:
    from pypdf import PdfReader

_INSTALL_HINT = "pip install 'birkin[office-advanced]'"


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


def inspect_pdf(
    path: Path, password: str | bytes | None = None
) -> tuple[dict[str, object], ParsedPdf]:
    source = path
    reader = _reader(source, password)
    encrypted = bool(reader.is_encrypted)
    if encrypted and password is None:
        locked = ParsedPdf(True, None, (), None, None)
        return _locked_state(), locked

    document = ParsedPdf(
        is_encrypted=encrypted,
        root_object=reader.root_object,
        pages=tuple(ParsedPage.from_object(page) for page in reader.pages),
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
    page_text: list[str] = []
    image_pages = 0
    for page in document.pages:
        page_text.append(page.extract_text() or "")
        image_pages += images_on_page(page) > 0
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
