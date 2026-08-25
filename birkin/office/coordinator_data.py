"""Typed parsing and integrity helpers for durable Office coordinator payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from .errors import DocumentError, DocumentErrorCode
from .export_policy import JSONValue
from .job_journal import OfficeJobJournal
from .proposal_integrity import proposal_digest as exact_proposal_digest


def canonical_office_home() -> Path:
    """Return the only production root trusted for Office source access."""
    from .. import config

    return config.birkin_home() / "office"


def coordinator_error(code: DocumentErrorCode, message: str) -> DocumentError:
    return DocumentError(code, "office_coordinator", message)


def required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise coordinator_error(
            DocumentErrorCode.INVALID_INPUT, f"{field} must be a non-empty string"
        )
    return value


def required_mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise coordinator_error(DocumentErrorCode.INVALID_INPUT, f"{field} must be an object")
    parsed: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise coordinator_error(
                DocumentErrorCode.INVALID_INPUT, f"{field} keys must be strings"
            )
        parsed[key] = item
    return parsed


def required_sequence(
    value: object, field: str
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise coordinator_error(DocumentErrorCode.INVALID_INPUT, f"{field} must be an array")
    return tuple(required_mapping(item, field) for item in value)


def json_value(value: object) -> JSONValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        raise coordinator_error(
            DocumentErrorCode.INVALID_INPUT, "operations must contain JSON values"
        )
    if isinstance(value, Mapping):
        parsed: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise coordinator_error(
                    DocumentErrorCode.INVALID_INPUT,
                    "operation object keys must be strings",
                )
            parsed[key] = json_value(item)
        return parsed
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [json_value(item) for item in value]
    raise coordinator_error(
        DocumentErrorCode.INVALID_INPUT, "operations must contain JSON values"
    )


def job_operations(
    snapshot: Mapping[str, object],
) -> tuple[Mapping[str, JSONValue], ...]:
    operations = required_sequence(snapshot.get("operations"), "operations")
    parsed: list[Mapping[str, JSONValue]] = []
    for operation in operations:
        value = json_value(operation)
        if not isinstance(value, dict):
            raise coordinator_error(
                DocumentErrorCode.INVALID_INPUT, "operation must be an object"
            )
        parsed.append(value)
    return tuple(parsed)


def proposal_digest(snapshot: Mapping[str, object]) -> str:
    preview = required_mapping(snapshot.get("preview"), "preview")
    return exact_proposal_digest(
        job_operations(snapshot),
        required_text(preview.get("source_sha256"), "preview source_sha256"),
        required_text(snapshot.get("outcome"), "outcome"),
    )


def job_journal(home: Path) -> OfficeJobJournal:
    return OfficeJobJournal(home / "jobs")
