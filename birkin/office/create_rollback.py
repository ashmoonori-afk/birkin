"""Rollback execution for durable Office creation jobs."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .create_journal import CreationJobJournal
from .errors import DocumentError, DocumentErrorCode
from .export_io import current_hash
from .job_runner import DocumentServiceRunner
from .service import DocumentService

_STAGE = "office_create_rollback"


def _error(message: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.PRECONDITION_FAILED,
        _STAGE,
        message,
    )


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise _error(f"{field} is invalid")
    return value


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise _error(f"{field} is invalid")
    return {str(key): item for key, item in value.items()}


def _verify_completed(
    rollback: Mapping[str, object],
    destination: Path,
    approval_id: str,
    authority: Mapping[str, object],
) -> None:
    restored = rollback.get("restored")
    expected_hash = rollback.get("destination_sha256")
    if (
        rollback.get("approval_id") != approval_id
        or rollback.get("approved_by") != authority.get("approved_by")
        or rollback.get("approved_via") != authority.get("approved_via")
        or not isinstance(restored, bool)
        or (expected_hash is not None and not isinstance(expected_hash, str))
        or current_hash(destination, _STAGE) != (expected_hash if restored else None)
    ):
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            _STAGE,
            "completed creation rollback state changed",
        )


def execute_creation_rollback(
    *,
    job_id: str,
    record: Mapping[str, object],
    export: Mapping[str, object],
    destination: Path,
    approval_id: str,
    authority: Mapping[str, object],
    service: DocumentService,
    journal: CreationJobJournal,
) -> dict[str, object]:
    """Rollback or verify one authenticated creation export."""
    if record.get("state") == "rolled_back":
        rollback = _mapping(
            record.get("rollback"),
            "rollback receipt",
        )
        _verify_completed(
            rollback,
            destination,
            approval_id,
            authority,
        )
        return rollback
    if record.get("state") != "exported":
        raise _error("exported Office creation job is required")
    runner = DocumentServiceRunner(
        service,
        export_root=destination.parent,
    )
    rolled_back = runner.rollback_export(export)
    result: dict[str, object] = {
        **rolled_back,
        "approval_id": approval_id,
        "approved_by": _text(
            authority.get("approved_by"),
            "rollback approver",
        ),
        "approved_via": _text(
            authority.get("approved_via"),
            "rollback approval channel",
        ),
    }
    journal.mark_rolled_back(job_id, result)
    return result


__all__ = ["execute_creation_rollback"]
