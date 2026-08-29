"""Shared values for approval-bound DOCX creation."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .artifact_serialization import canonical_integrity_json
from .errors import DocumentError, DocumentErrorCode
from .export_types import JSONValue

FORMAT = "docx"
VERSION = 1
CATEGORY = "office_create"
PAYLOAD_KEYS = frozenset(
    {
        "version",
        "job_id",
        "creation_digest",
        "format",
        "content",
        "content_sha256",
        "outcome",
        "destination",
        "allowlist_root",
        "proposer",
        "overwrite_approved",
        "authority_digest",
        "output_name",
    }
)


@dataclass(frozen=True, slots=True)
class OfficeCreationRequest:
    """Trusted creation intent parsed at a user-facing boundary."""

    request_text: str
    paragraphs: tuple[str, ...]
    outcome: str
    destination: Path
    overwrite_approved: bool = False


@dataclass(frozen=True, slots=True)
class OfficeCreationCaller:
    """Trusted actor and export root supplied outside the model payload."""

    allowlist_root: Path
    actor: str


def creation_error(message: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.PRECONDITION_FAILED,
        "office_create",
        message,
    )


def required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise creation_error(f"{name} must be a non-empty string")
    return value


def parse_paragraphs(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise creation_error("content paragraphs must be an array")
    paragraphs = tuple(
        required_text(paragraph, "content paragraph") for paragraph in value
    )
    if not paragraphs:
        raise creation_error("content paragraphs must not be empty")
    return paragraphs


def creation_content(
    paragraphs: tuple[str, ...],
) -> dict[str, JSONValue]:
    return {"paragraphs": list(paragraphs)}


def content_sha256(content: Mapping[str, JSONValue]) -> str:
    return hashlib.sha256(canonical_integrity_json(content).encode("utf-8")).hexdigest()


def creation_operations(
    approved_content_sha256: str,
    job_id: str,
) -> tuple[dict[str, JSONValue], ...]:
    return (
        {
            "operation": "create",
            "format": FORMAT,
            "content_sha256": approved_content_sha256,
            "job_id": job_id,
        },
    )
