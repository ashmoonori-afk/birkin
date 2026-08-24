"""Typed Office Work OS failures with safe evidence envelopes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import FrozenInstanceError, dataclass, field
from enum import Enum
from typing import ClassVar, cast

from typing_extensions import override

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


# This payload is selectively immutable because BaseException owns mutable traceback state.
@dataclass
class DocumentError(Exception):
    """Typed failure with immutable payload fields and writable exception state."""

    code: DocumentErrorCode
    stage: str
    message: str
    retryable: bool = False
    artifact_sha256: str | None = None
    locator: dict[str, object] | None = None
    details: dict[str, object] = field(default_factory=dict)

    _IMMUTABLE_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "code",
            "stage",
            "message",
            "retryable",
            "artifact_sha256",
            "locator",
            "details",
        }
    )

    @override
    def __setattr__(self, name: str, value: object) -> None:
        if name in self._IMMUTABLE_FIELDS and name in self.__dict__:
            raise FrozenInstanceError(f"cannot assign to field {name!r}")
        super().__setattr__(name, value)

    @override
    def __delattr__(self, name: str) -> None:
        if name in self._IMMUTABLE_FIELDS:
            raise FrozenInstanceError(f"cannot delete field {name!r}")
        super().__delattr__(name)

    def add_note(self, note: object) -> None:
        """Attach an operator note on every supported Python version."""
        if not isinstance(note, str):
            raise TypeError("note must be a str")
        notes_value = cast(object, getattr(self, "__notes__", None))
        if notes_value is None:
            notes = []
            super().__setattr__("__notes__", notes)
        elif isinstance(notes_value, list):
            raw_notes = cast(list[object], notes_value)
            if not all(isinstance(item, str) for item in raw_notes):
                raise TypeError("__notes__ must be a list of str")
            notes = cast(list[str], raw_notes)
        else:
            raise TypeError("__notes__ must be a list of str")
        notes.append(note)

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
