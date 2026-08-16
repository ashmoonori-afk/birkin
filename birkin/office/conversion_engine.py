"""Budget-bound, deterministic Office-to-text conversion."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from .adapters.catalog import supported_formats
from .conversion_audit import LOSS_CATEGORIES, audit_source, normalize_budget
from .conversion_receipt import build_receipt
from .errors import DocumentError, DocumentErrorCode
from .service_types import ConvertedDocument, ExtractionResult
from .service_workspace import MAX_CONTENT_CHARS, DocumentWorkspace

_SUPPORTED_SOURCES = frozenset(supported_formats("convert"))


class TextExtractor(Protocol):
    def __call__(
        self, source: Mapping[str, object], *, max_chars: int
    ) -> ExtractionResult: ...


def _refuse_unsafe(
    observed: Mapping[str, int], active: list[dict[str, str]]
) -> None:
    if observed["macro_active_content"]:
        raise DocumentError(
            DocumentErrorCode.POLICY_DENIED,
            "convert",
            "active content conversion is refused",
            details={"active_content": active, "executed": False},
        )
    if observed["signature_encryption"]:
        raise DocumentError(
            DocumentErrorCode.POLICY_DENIED,
            "convert",
            "signed or encrypted document conversion is refused",
            details={
                "category": "signature_encryption",
                "observed": observed["signature_encryption"],
            },
        )


def _enforce_budget(observed: Mapping[str, int], budget: Mapping[str, int]) -> None:
    exceeded = [
        {
            "category": category,
            "observed": observed[category],
            "budget": budget[category],
        }
        for category in LOSS_CATEGORIES
        if observed[category] > budget[category]
    ]
    if exceeded:
        raise DocumentError(
            DocumentErrorCode.LOSSY_WRITE_BLOCKED,
            "convert",
            "observed conversion loss exceeds the explicit budget",
            details={"exceeded": exceeded, "published": False},
        )


def _payload(extraction: ExtractionResult) -> bytes:
    if extraction["truncation"]["truncated"]:
        raise DocumentError(
            DocumentErrorCode.LIMIT_EXCEEDED,
            "convert",
            "extracted text exceeds the conversion limit",
            details={"limits": extraction["limits"]},
        )
    text = extraction["text"]
    payload = (text + ("\n" if text else "")).encode("utf-8")
    try:
        reopened = payload.decode("utf-8")
    except UnicodeDecodeError as exc:  # pragma: no cover - encode/decode invariant
        raise DocumentError(
            DocumentErrorCode.VALIDATION_FAILED,
            "validate",
            "text output is not valid UTF-8",
        ) from exc
    if reopened.removesuffix("\n") != text:
        raise DocumentError(
            DocumentErrorCode.VALIDATION_FAILED,
            "validate",
            "text output does not match the extracted projection",
        )
    return payload


def convert_document(
    workspace: DocumentWorkspace,
    source: Mapping[str, object],
    *,
    target_format: str,
    output_name: str,
    extract: TextExtractor,
    loss_budget: Mapping[str, object] | None = None,
) -> ConvertedDocument:
    """Convert a supported immutable source to UTF-8 text or fail unpublished."""
    target = target_format.strip().lower().lstrip(".")
    if target != "txt":
        raise DocumentError(
            DocumentErrorCode.CAPABILITY_UNAVAILABLE,
            "convert",
            "only deterministic text conversion is available",
            details={"supported": ["txt"], "native_office_conversion": False},
        )
    output = workspace.output_path(output_name, ".txt")
    budget = normalize_budget(loss_budget)
    source_path = workspace.resolve_artifact(source).resolve()
    if not source_path.is_relative_to(workspace.home):
        raise DocumentError(
            DocumentErrorCode.PERMISSION_DENIED,
            "import",
            "document source escapes the configured home",
        )
    source_format = source_path.suffix.lower().lstrip(".")
    if source_format not in _SUPPORTED_SOURCES:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_FORMAT,
            "probe",
            f"unsupported conversion source: {source_format}",
            details={"supported": sorted(_SUPPORTED_SOURCES)},
        )
    source_sha256 = workspace.hash_file(source_path)
    observed, active = audit_source(source_path, source_format)
    _refuse_unsafe(observed, active)
    _enforce_budget(observed, budget)
    extraction = extract(source, max_chars=MAX_CONTENT_CHARS)
    if extraction["source"]["sha256"] != source_sha256:
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "convert",
            "extraction identity does not match the conversion source",
        )
    payload = _payload(extraction)
    output_sha256 = hashlib.sha256(payload).hexdigest()
    descriptor, name = tempfile.mkstemp(dir=workspace.drafts, suffix=".txt")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            _ = stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.read_bytes() != payload:
            raise DocumentError(
                DocumentErrorCode.VALIDATION_FAILED,
                "validate",
                "text output failed exact reopen validation",
            )
        current_source_sha256 = workspace.hash_file(source_path)
        if current_source_sha256 != source_sha256:
            raise DocumentError(
                DocumentErrorCode.SOURCE_CHANGED,
                "validate",
                "source changed during conversion",
                artifact_sha256=current_source_sha256,
            )
        receipt = build_receipt(
            source_format=source_format,
            source_sha256=source_sha256,
            output_sha256=output_sha256,
            output_name=output_name,
            budget=budget,
            observed=observed,
            extraction=extraction,
            source_immutable=True,
            output_bytes=len(payload),
            preview=extraction["text"][:200],
        )
        try:
            os.link(temporary, output)
        except FileExistsError as exc:
            raise DocumentError(
                DocumentErrorCode.OUTPUT_EXISTS, "emit", "output exists"
            ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    artifact = workspace.artifact(output, source)
    if artifact["content_hash"] != output_sha256:
        output.unlink(missing_ok=True)
        raise DocumentError(
            DocumentErrorCode.VALIDATION_FAILED,
            "validate",
            "published output hash does not match the validated output",
        )
    final_source_sha256 = workspace.hash_file(source_path)
    if final_source_sha256 != source_sha256:
        output.unlink(missing_ok=True)
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "emit",
            "source changed while the conversion was published",
            artifact_sha256=final_source_sha256,
        )
    return {
        "status": "draft",
        "draft_artifact": artifact,
        "source_sha256": source_sha256,
        "output_sha256": output_sha256,
        "source_format": source_format,
        "target_format": "txt",
        "receipt": receipt,
    }
