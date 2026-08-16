"""Typed Office Work OS failures with safe evidence envelopes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from .artifact_serialization import canonical_json, sanitize_data


class DocumentErrorCode(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    SOURCE_CHANGED = "SOURCE_CHANGED"
    PACKAGE_INVALID = "PACKAGE_INVALID"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    EXTERNAL_RELATIONSHIP_BLOCKED = "EXTERNAL_RELATIONSHIP_BLOCKED"
    NODE_NOT_FOUND = "NODE_NOT_FOUND"
    AMBIGUOUS_LOCATOR = "AMBIGUOUS_LOCATOR"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    UNSUPPORTED_EDIT = "UNSUPPORTED_EDIT"
    LOSSY_WRITE_BLOCKED = "LOSSY_WRITE_BLOCKED"
    OUTPUT_EXISTS = "OUTPUT_EXISTS"
    STORAGE_EXHAUSTED = "STORAGE_EXHAUSTED"
    RENDER_UNAVAILABLE = "RENDER_UNAVAILABLE"
    RENDER_FAILED = "RENDER_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    POLICY_DENIED = "POLICY_DENIED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class DocumentError(Exception):
    code: DocumentErrorCode
    stage: str
    message: str
    retryable: bool = False
    artifact_sha256: str | None = None
    locator: dict[str, object] | None = None
    details: dict[str, object] = field(default_factory=dict)

    def envelope(self, *, secrets: Iterable[str] = ()) -> dict[str, object]:
        error = {
            "code": self.code.value,
            "stage": self.stage,
            "message": self.message[:2000],
            "retryable": self.retryable,
            "artifact_sha256": self.artifact_sha256,
            "locator": self.locator,
            "details": self.details,
        }
        safe = sanitize_data({"error": error}, secrets=secrets)
        if not isinstance(safe, dict):  # pragma: no cover - fixed local shape
            raise TypeError("error envelope must be an object")
        return dict[str, object](safe)

    def canonical_envelope(self, *, secrets: Iterable[str] = ()) -> str:
        return canonical_json(self.envelope(secrets=secrets))
