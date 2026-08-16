"""Truthful read-only PDF adapter."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..errors import DocumentError, DocumentErrorCode
from .pdf_capabilities import pdf_mutation_capabilities
from .pdf_mutation import (
    PDF_MUTATION_OPERATIONS,
    PdfMutationOperation,
    parse_pdf_mutation_operation,
)
from .pdf_state import inspect_pdf
from .pdf_types import array_items, mapping


def _refusal(
    stage: str,
    message: str,
    reason: str,
    code: DocumentErrorCode = DocumentErrorCode.CAPABILITY_UNAVAILABLE,
    *,
    details: dict[str, object] | None = None,
) -> DocumentError:
    payload = {"reason": reason, **(details or {})}
    return DocumentError(code, stage, message, details=payload)


def _revision_count(raw: bytes) -> int:
    starts = len(re.findall(rb"(?m)^startxref\s*$", raw))
    endings = len(re.findall(rb"(?m)^%%EOF\s*$", raw))
    return max(starts, endings)


def _has_doc_mdp(state: dict[str, object]) -> bool:
    signatures = mapping(state.get("signatures"))
    if signatures is None:
        return False
    for item in array_items(signatures.get("items")):
        signature = mapping(item)
        if signature is not None and signature.get("doc_mdp") is True:
            return True
    return False


class PdfAdapter:
    format: str = "pdf"

    def __init__(self, password: str | bytes | None = None):
        self._password: str | bytes | None = password

    def inspect(
        self, path: Path, *, password: str | bytes | None = None
    ) -> dict[str, object]:
        source = path
        raw = source.read_bytes()
        state, _ = inspect_pdf(source, self._password if password is None else password)
        revisions = _revision_count(raw)
        state["source_sha256"] = hashlib.sha256(raw).hexdigest()
        state["revision_history"] = {
            "marker_count": revisions,
            "multiple_revisions_detected": revisions > 1,
            "incremental_update_safety": "unsupported",
        }
        capabilities = mapping(state.get("capabilities"))
        exposed = (
            {str(key): value for key, value in capabilities.items()}
            if capabilities is not None
            else {}
        )
        mutations = pdf_mutation_capabilities(
            str(state.get("form_type", "unknown")),
            str(state.get("content_type", "unknown")),
            encrypted=state.get("encrypted") is True,
            credential_required=state.get("credential_required") is True,
            signed=state.get("signed") is True,
            doc_mdp=_has_doc_mdp(state),
            multiple_revisions=revisions > 1,
        )
        exposed.update(mutations)
        exposed["fill"] = dict(mutations["form_fill"])
        exposed["patch"] = dict(mutations["body_edit"])
        state["capabilities"] = exposed
        return state

    def mutation_decision(
        self,
        path: Path,
        operation: PdfMutationOperation | str,
        *,
        password: str | bytes | None = None,
    ) -> dict[str, object]:
        parsed = parse_pdf_mutation_operation(operation)
        if parsed is None:
            raise _refusal(
                "apply",
                "unknown PDF mutation operation",
                "pdf_mutation_operation_unknown",
                DocumentErrorCode.INVALID_INPUT,
                details={"supported_operations": list(PDF_MUTATION_OPERATIONS)},
            )
        state = self.inspect(path, password=password)
        capabilities = mapping(state.get("capabilities"))
        decision = (
            mapping(capabilities.get(parsed)) if capabilities is not None else None
        )
        if decision is None:
            raise _refusal(
                "apply",
                "PDF mutation decision is unavailable",
                "pdf_mutation_decision_unavailable",
            )
        return {str(key): value for key, value in decision.items()}

    def extract(
        self, path: Path, *, password: str | bytes | None = None
    ) -> list[dict[str, object]]:
        source = path
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        state, reader = inspect_pdf(
            source, self._password if password is None else password
        )
        if state["credential_required"]:
            raise _refusal(
                "extract",
                "PDF content requires a user-supplied password",
                "pdf_password_required",
                DocumentErrorCode.PERMISSION_DENIED,
            )
        security = mapping(state["security"])
        if security is not None and security.get("text_extraction_allowed") is False:
            raise _refusal(
                "extract",
                "PDF permissions disallow text extraction",
                "pdf_extraction_permission_denied",
                DocumentErrorCode.PERMISSION_DENIED,
            )
        if state["form_type"] == "xfa":
            raise _refusal(
                "extract",
                "XFA content extraction is unsupported",
                "pdf_xfa_content_unsupported",
            )
        if state["content_type"] == "image_only":
            raise _refusal(
                "extract",
                "image-only PDF extraction requires OCR",
                "pdf_image_only_requires_ocr",
            )
        if state["content_type"] == "backend_unavailable":
            raise _refusal(
                "extract",
                "PDF text extraction requires the approved pypdf package",
                "pdf_parser_unavailable",
                DocumentErrorCode.CAPABILITY_UNAVAILABLE,
            )
        spans: list[dict[str, object]] = []
        for page_number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            for line in (item.strip() for item in text.splitlines()):
                if line:
                    spans.append(
                        {
                            "text": line,
                            "source_sha256": digest,
                            "page_no": page_number,
                            "bbox": None,
                            "object_ref": None,
                            "method": "pypdf_native_text",
                        }
                    )
        return spans

    def fill(
        self,
        path: Path,
        operation: dict[str, object],
        *,
        password: str | bytes | None = None,
    ) -> None:
        _ = operation
        decision = self.mutation_decision(path, "form_fill", password=password)
        raise self._mutation_refusal(decision)

    def patch(
        self,
        path: Path,
        operation: dict[str, object],
        *,
        password: str | bytes | None = None,
    ) -> None:
        raw_operation = operation.get("type", operation.get("operation"))
        parsed = parse_pdf_mutation_operation(raw_operation)
        # An untyped legacy patch request remains a truthful generic refusal.
        # Named operations use the state-aware decision surface below.
        if raw_operation is None:
            raise _refusal(
                "apply",
                "general PDF content rewrite is unsupported",
                "pdf_general_mutation_unsupported",
                DocumentErrorCode.UNSUPPORTED_EDIT,
            )
        if parsed is None:
            _ = self.mutation_decision(path, str(raw_operation), password=password)
            raise AssertionError("unreachable")
        decision = self.mutation_decision(path, parsed, password=password)
        raise self._mutation_refusal(decision)

    @staticmethod
    def _mutation_refusal(decision: dict[str, object]) -> DocumentError:
        reason = str(decision.get("reason", "pdf_mutation_decision_unavailable"))
        operation = str(decision.get("operation", "unknown"))
        return _refusal(
            "apply",
            f"PDF {operation} is unsupported for this document state",
            reason,
            DocumentErrorCode.UNSUPPORTED_EDIT,
            details={
                key: value
                for key, value in decision.items()
                if key not in {"state", "reason"}
            },
        )
