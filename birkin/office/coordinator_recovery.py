"""Crash recovery for approval-owned Office coordinator executions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing_extensions import assert_never

from .artifact_serialization import canonical_json
from .coordinator_data import (
    coordinator_error,
    job_journal,
    job_operations,
    proposal_digest,
    required_mapping,
    required_text,
)
from .errors import DocumentErrorCode
from .export_policy import ExportRequest
from .job import OfficeJob
from .job_runner import DocumentServiceRunner
from .job_types import OfficeJobState
from .service import DocumentService


@dataclass(frozen=True, slots=True)
class ApprovedAuthority:
    """Exact authority persisted by the canonical approval record."""

    proposal_digest: str
    source_sha256: str
    actor: str
    destination: Path
    allowlist_root: Path
    overwrite_approved: bool


def _authority(payload: Mapping[str, object]) -> ApprovedAuthority:
    overwrite = payload.get("overwrite_approved", False)
    if not isinstance(overwrite, bool):
        raise coordinator_error(
            DocumentErrorCode.POLICY_DENIED, "overwrite approval must be boolean"
        )
    return ApprovedAuthority(
        proposal_digest=required_text(payload.get("proposal_digest"), "proposal_digest"),
        source_sha256=required_text(payload.get("source_sha256"), "source_sha256"),
        actor=required_text(payload.get("actor"), "actor"),
        destination=Path(required_text(payload.get("destination"), "destination")),
        allowlist_root=Path(required_text(payload.get("allowlist_root"), "allowlist_root")),
        overwrite_approved=overwrite,
    )


def _require_queue_authority(
    approval_id: str, payload: Mapping[str, object]
) -> None:
    from .. import store

    record = store.get_pending(approval_id)
    if (
        record is None
        or record.get("status") != "executing"
        or record.get("category") != "office_job"
        or record.get("payload") != payload
    ):
        raise coordinator_error(
            DocumentErrorCode.POLICY_DENIED,
            "Office approval authority is not executing this payload",
        )


def _verify_snapshot(
    snapshot: Mapping[str, object], authority: ApprovedAuthority, state: OfficeJobState
) -> None:
    if proposal_digest(snapshot) != authority.proposal_digest:
        raise coordinator_error(
            DocumentErrorCode.POLICY_DENIED, "approved Office proposal digest changed"
        )
    preview = required_mapping(snapshot.get("preview"), "preview")
    if preview.get("source_sha256") != authority.source_sha256:
        raise coordinator_error(
            DocumentErrorCode.POLICY_DENIED, "approved Office source digest changed"
        )
    match state:
        case OfficeJobState.approval_requested:
            if snapshot.get("approval") is not None or snapshot.get("approved_digest") is not None:
                raise coordinator_error(
                    DocumentErrorCode.POLICY_DENIED,
                    "unapproved Office snapshot contains approval authority",
                )
        case (
            OfficeJobState.approved
            | OfficeJobState.executed
            | OfficeJobState.validated
            | OfficeJobState.exported
        ):
            approval = required_mapping(snapshot.get("approval"), "approval")
            if (
                snapshot.get("approved_digest") != authority.proposal_digest
                or approval.get("proposal_digest") != authority.proposal_digest
                or approval.get("actor") != authority.actor
                or approval.get("decision") != "approved"
            ):
                raise coordinator_error(
                    DocumentErrorCode.POLICY_DENIED,
                    "durable Office approval does not match queue authority",
                )
        case (
            OfficeJobState.input_captured
            | OfficeJobState.outcome_declared
            | OfficeJobState.operations_proposed
            | OfficeJobState.preview_ready
            | OfficeJobState.rejected
            | OfficeJobState.failed
        ):
            raise coordinator_error(
                DocumentErrorCode.POLICY_DENIED,
                "Office job is not resumable from its durable state",
            )
        case unreachable:
            assert_never(unreachable)


def _verify_current_source(
    service: DocumentService,
    snapshot: Mapping[str, object],
    authority: ApprovedAuthority,
) -> None:
    source = required_mapping(snapshot.get("source"), "source")
    current = service.inspect_document(source)
    identity = required_mapping(current.get("source"), "inspection source")
    if identity.get("sha256") != authority.source_sha256:
        raise coordinator_error(
            DocumentErrorCode.POLICY_DENIED, "Office source changed after approval request"
        )


def _resume(job: OfficeJob, request: ExportRequest, actor: str) -> None:
    while True:
        match job.state:
            case OfficeJobState.approval_requested:
                job.approve(actor=actor)
            case OfficeJobState.approved:
                _ = job.execute()
            case OfficeJobState.executed:
                validation = job.validate()
                if validation.get("valid") is not True:
                    raise coordinator_error(
                        DocumentErrorCode.VALIDATION_FAILED,
                        "executed Office draft failed validation",
                    )
            case OfficeJobState.validated:
                snapshot = job.to_dict()
                if snapshot.get("rollback") is not None:
                    raise coordinator_error(
                        DocumentErrorCode.POLICY_DENIED,
                        "rolled-back Office export cannot resume automatically",
                    )
                if snapshot.get("publication") is None:
                    format_name = required_text(snapshot.get("format_name"), "format_name")
                    _ = job.publish(output_name=f"{snapshot['job_id']}.validated.{format_name}")
                else:
                    _ = job.export(request)
            case OfficeJobState.exported:
                return
            case (
                OfficeJobState.input_captured
                | OfficeJobState.outcome_declared
                | OfficeJobState.operations_proposed
                | OfficeJobState.preview_ready
                | OfficeJobState.rejected
                | OfficeJobState.failed
            ):
                raise coordinator_error(
                    DocumentErrorCode.POLICY_DENIED,
                    "Office job is not resumable from its durable state",
                )
            case unreachable:
                assert_never(unreachable)


def execute_approved_office_job(
    payload: Mapping[str, object], *, approval_id: str | None
) -> str:
    """Resume exactly one approval-owned Office mutation under its process lock."""
    from .. import config, store

    if approval_id is None:
        raise coordinator_error(
            DocumentErrorCode.POLICY_DENIED,
            "Office execution requires an approved queue claim",
        )
    _require_queue_authority(approval_id, payload)
    job_id = required_text(payload.get("job_id"), "job_id")
    authority = _authority(payload)
    home = config.birkin_home()
    journal = job_journal(home)
    with store.file_lock(journal.path_for(job_id), timeout=0):
        _require_queue_authority(approval_id, payload)
        service = DocumentService(home)
        runner = DocumentServiceRunner(service, export_root=authority.allowlist_root)
        job = journal.restore(job_id, runner=runner)
        snapshot = job.to_dict()
        _verify_snapshot(snapshot, authority, job.state)
        if job.state in {OfficeJobState.approval_requested, OfficeJobState.approved}:
            _verify_current_source(service, snapshot, authority)
        request = ExportRequest(
            destination=authority.destination,
            actor=authority.actor,
            proposal_digest=authority.proposal_digest,
            operations=job_operations(snapshot),
            overwrite_approved=authority.overwrite_approved,
        )
        _resume(job, request, authority.actor)
        return canonical_json(job.receipt())
