"""Approval-gated rollback of one durable Office export receipt."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from birkin import approvals, config, store

from .coordinator_data import canonical_office_home, job_journal
from .create_journal import CreationJobJournal
from .create_rollback import execute_creation_rollback
from .errors import DocumentError, DocumentErrorCode
from .export_io import current_hash
from .job_runner import DocumentServiceRunner
from .receipt_auth import authenticate_receipt
from .retention import purge_expired_office_state
from .service import DocumentService

_STAGE = "office_rollback"


def prepare_rollback(job_id: str) -> dict[str, object]:
    home = canonical_office_home()
    _ = DocumentService(home)
    _ = purge_expired_office_state(home)
    job_id = _job_id(job_id)
    record = _job_record(home, job_id)
    _require_exported(record)
    export = _mapping(record.get("export"), "export receipt")
    _ = authenticate_receipt(export, home)
    destination = _text(export.get("path"), "export destination")
    receipt_hmac = _text(
        export.get("receipt_hmac"),
        "export receipt authentication",
    )
    return {
        "job_id": job_id,
        "destination": destination,
        "receipt_hmac": receipt_hmac,
    }


def request_rollback(
    job_id: str,
    *,
    origin: str,
    cfg: dict[str, object] | None = None,
) -> dict[str, object]:
    rollback = prepare_rollback(job_id)
    queued = approvals.propose(
        category="office_rollback",
        title="Office 내보내기 되돌리기",
        description=(
            "내보내기 전 상태로 저장 위치를 복원합니다: "
            f"{rollback['destination']}"
        ),
        payload=rollback,
        cfg=cfg or {},
        origin=origin,
    )
    return {
        **queued,
        "category": "office_rollback",
        "approval": rollback,
    }


def execute_approved_rollback(
    payload: Mapping[str, object],
    *,
    approval_id: str | None,
) -> str:
    if approval_id is None:
        raise _error(
            DocumentErrorCode.POLICY_DENIED,
            "rollback approval authority is required",
        )
    job_id = _job_id(_text(payload.get("job_id"), "job id"))
    approved_destination = _text(
        payload.get("destination"),
        "approved rollback destination",
    )
    approved_receipt_hmac = _text(
        payload.get("receipt_hmac"),
        "approved export receipt authentication",
    )
    home = canonical_office_home()
    service = DocumentService(home)
    journal = job_journal(home)
    creation_journal = CreationJobJournal(home)
    creation_record = creation_journal.latest(job_id)
    path = (
        creation_journal.path_for(job_id)
        if creation_record
        else journal.path_for(job_id)
    )
    approval_path = config.pending_dir() / f"{approval_id}.json"
    with store.file_lock(approval_path, timeout=0):
        authority = _queue_authority(approval_id, payload)
        with store.file_lock(path, timeout=0):
            authority = _queue_authority(approval_id, payload)
            record = _job_record(home, job_id)
            export = _mapping(record.get("export"), "export receipt")
            authenticated = authenticate_receipt(export, home)
            if not authenticated or export.get("receipt_hmac") != approved_receipt_hmac:
                raise _error(
                    DocumentErrorCode.PERMISSION_DENIED,
                    "approved export receipt changed",
                )
            destination = Path(_text(export.get("path"), "export destination"))
            if str(destination) != approved_destination:
                raise _error(
                    DocumentErrorCode.PERMISSION_DENIED,
                    "approved rollback destination changed",
                )
            if record.get("kind") == "office_create":
                return _json(execute_creation_rollback(
                    job_id=job_id,
                    record=record,
                    export=export,
                    destination=destination,
                    approval_id=approval_id,
                    authority=authority,
                    service=service,
                    journal=creation_journal,
                ))
            if record.get("state") == "validated":
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
                return _json(rollback)
            _require_exported(record)
            runner = DocumentServiceRunner(
                service,
                export_root=destination.parent,
            )
            job = journal.restore(job_id, runner=runner)
            result = job.rollback_export(
                approval_id=approval_id,
                approved_by=_text(authority.get("approved_by"), "rollback approver"),
                approved_via=_text(
                    authority.get("approved_via"),
                    "rollback approval channel",
                ),
            )
    return _json(result)


def _queue_authority(
    approval_id: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    record = store.get_pending(approval_id)
    if (
        record is None
        or record.get("status") != "executing"
        or record.get("category") != "office_rollback"
        or record.get("payload") != payload
        or not record.get("approved_by")
        or not record.get("approved_via")
    ):
        raise _error(
            DocumentErrorCode.POLICY_DENIED,
            "rollback approval authority is not executing this payload",
        )
    return record


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
        or current_hash(destination, _STAGE)
        != (expected_hash if restored else None)
    ):
        raise _error(
            DocumentErrorCode.SOURCE_CHANGED,
            "completed rollback state changed",
        )


def _json(value: Mapping[str, object]) -> str:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _job_record(home: Path, job_id: str) -> dict[str, object]:
    creation = CreationJobJournal(home).latest(job_id)
    if creation:
        if creation.get("job_id") != job_id:
            raise _error(
                DocumentErrorCode.PRECONDITION_FAILED,
                "durable Office creation job is unavailable",
            )
        return creation
    record = job_journal(home).latest(job_id)
    if record.get("job_id") != job_id:
        raise _error(
            DocumentErrorCode.PRECONDITION_FAILED,
            "durable Office job is unavailable",
        )
    return record


def _require_exported(record: Mapping[str, object]) -> None:
    if record.get("state") != "exported":
        raise _error(
            DocumentErrorCode.PRECONDITION_FAILED,
            "exported Office job is required",
        )


def _job_id(value: str) -> str:
    if len(value) != 32 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise _error(
            DocumentErrorCode.INVALID_INPUT,
            "job id is invalid",
        )
    return value


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _error(
            DocumentErrorCode.PRECONDITION_FAILED,
            f"{field} is invalid",
        )
    mapping = cast("Mapping[object, object]", value)
    parsed: dict[str, object] = {}
    for key, item in mapping.items():
        if not isinstance(key, str):
            raise _error(
                DocumentErrorCode.PRECONDITION_FAILED,
                f"{field} is invalid",
            )
        parsed[key] = item
    return parsed


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise _error(
            DocumentErrorCode.INVALID_INPUT,
            f"{field} is invalid",
        )
    return value


def _error(
    code: DocumentErrorCode,
    message: str,
) -> DocumentError:
    return DocumentError(code, _STAGE, message)
