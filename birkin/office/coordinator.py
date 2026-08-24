"""Canonical approval coordinator for durable Office document mutations."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, final, runtime_checkable

from .artifact_serialization import canonical_json
from .errors import DocumentError, DocumentErrorCode
from .export_policy import JSONValue, ExportRequest
from .job import OfficeJob
from .job_journal import OfficeJobJournal
from .job_runner import DocumentServiceRunner
from .job_types import OfficeJobState
from .preview_semantics import summarize_operations
from .service import DocumentService
from .service_workspace import DocumentWorkspace
from .skill_router import route_office_request


@runtime_checkable
class _StructuredMapping(Protocol):
    def items(self) -> Iterable[tuple[str, object]]: ...


@runtime_checkable
class _ObjectSequence(Protocol):
    def __iter__(self) -> Iterator[object]: ...


@dataclass(frozen=True, slots=True)
class OfficeCaller:
    """Trusted actor and filesystem policy supplied by ToolContext."""

    home: Path
    allowlist_root: Path
    actor: str


@dataclass(frozen=True, slots=True)
class OfficeMutationRequest:
    """Parsed mutation proposal received at the document-tool boundary."""

    request_text: str
    source: Mapping[str, object]
    outcome: str
    operations: tuple[Mapping[str, object], ...]
    destination: Path
    overwrite_approved: bool = False


def _error(code: DocumentErrorCode, message: str) -> DocumentError:
    return DocumentError(code, "office_coordinator", message)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise _error(DocumentErrorCode.INVALID_INPUT, f"{field} must be a non-empty string")
    return value


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, _StructuredMapping):
        raise _error(DocumentErrorCode.INVALID_INPUT, f"{field} must be an object")
    return dict(value.items())


def _sequence(value: object, field: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _error(DocumentErrorCode.INVALID_INPUT, f"{field} must be an array")
    return tuple(_mapping(item, field) for item in value)


def _json_value(value: object) -> JSONValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        raise _error(DocumentErrorCode.INVALID_INPUT, "operations must contain JSON values")
    if isinstance(value, _StructuredMapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, _ObjectSequence):
        return [_json_value(item) for item in value]
    raise _error(DocumentErrorCode.INVALID_INPUT, "operations must contain JSON values")


def _job_operations(snapshot: Mapping[str, object]) -> tuple[Mapping[str, JSONValue], ...]:
    operations = _sequence(snapshot.get("operations"), "operations")
    parsed: list[Mapping[str, JSONValue]] = []
    for operation in operations:
        value = _json_value(operation)
        if not isinstance(value, dict):
            raise _error(DocumentErrorCode.INVALID_INPUT, "operation must be an object")
        parsed.append(value)
    return tuple(parsed)


def _proposal_digest(snapshot: Mapping[str, object]) -> str:
    preview = _mapping(snapshot.get("preview"), "preview")
    source_sha256 = _text(preview.get("source_sha256"), "preview source_sha256")
    outcome = _text(snapshot.get("outcome"), "outcome")
    proposal = {
        "operations": [dict(item) for item in _sequence(snapshot.get("operations"), "operations")],
        "source_sha256": source_sha256,
        "outcome": outcome,
    }
    return hashlib.sha256(canonical_json(proposal).encode("utf-8")).hexdigest()


def _semantic_summaries(
    preview: Mapping[str, object], operations: tuple[Mapping[str, object], ...]
) -> list[dict[str, str]]:
    try:
        return [
            {
                "location": summary["location"],
                "before": summary["before"],
                "after": summary["after"],
                "summary": summary["summary"],
            }
            for summary in summarize_operations(preview, operations)
        ]
    except DocumentError:
        if len(operations) != 1:
            raise
        container = _mapping(preview.get("preview"), "structured preview")
        nodes = _sequence(container.get("nodes"), "structured preview nodes")
        if len(nodes) != 1:
            raise
        operation = operations[0]
        node = nodes[0]
        before = _text(node.get("text"), "preview node text")
        after = _text(str(operation.get("value", "")), "operation value")
        location_value = (
            operation.get("cell")
            or operation.get("field")
            or operation.get("placeholder_idx")
        )
        location = _text(str(location_value or ""), "operation location")
        return [{
            "location": location,
            "before": before,
            "after": after,
            "summary": f"Replace {location}: {before} -> {after}",
        }]


def _journal(home: Path) -> OfficeJobJournal:
    return OfficeJobJournal(home / "office" / "jobs")


@final
class OfficeCoordinator:
    """Prepare one reviewable Office job without executing its mutation."""

    def __init__(self, caller: OfficeCaller) -> None:
        self._caller = caller
        self._service = DocumentService(caller.home)

    def request(self, request: OfficeMutationRequest) -> dict[str, object]:
        """Inspect, preview, summarize, persist, and queue one canonical approval."""
        inspection = self._service.inspect_document(request.source)
        format_name = _text(inspection.get("format"), "inspection format")
        source_identity = _mapping(inspection.get("source"), "inspection source")
        source_sha256 = _text(source_identity.get("sha256"), "source sha256")
        route = route_office_request(
            request.request_text,
            artifact_names=(_text(request.source.get("uri"), "source uri"),),
        )
        if route is None or route.conflict or route.format_name != format_name:
            raise _error(DocumentErrorCode.POLICY_DENIED, "request does not route to the inspected Office format")
        policy = DocumentWorkspace(self._caller.home).export_policy(
            self._caller.allowlist_root
        )
        destination = policy.resolve_destination(request.destination)
        preview = self._service.render_artifact(
            request.source, output_format="structured_preview"
        )
        summaries = _semantic_summaries(preview, request.operations)
        job = OfficeJob(
            job_id=uuid.uuid4().hex,
            format_name=format_name,
            source=request.source,
            runner=DocumentServiceRunner(
                self._service, export_root=self._caller.allowlist_root
            ),
            journal=_journal(self._caller.home),
        )
        job.declare_outcome(request.outcome)
        job.propose_operations(request.operations)
        _ = job.build_preview()
        approval = job.request_approval()
        payload = {
            "job_id": approval["job_id"],
            "proposal_digest": approval["proposal_digest"],
            "source_sha256": source_sha256,
            "destination": str(destination),
            "allowlist_root": str(self._caller.allowlist_root.resolve(strict=True)),
            "actor": self._caller.actor,
            "overwrite_approved": request.overwrite_approved,
            "semantic_summaries": summaries,
        }
        return payload


def execute_approved_office_job(
    payload: Mapping[str, object], *, approval_id: str | None
) -> str:
    """Restore and execute only a payload owned by the executing approval record."""
    from .. import config, store

    if approval_id is None:
        raise _error(DocumentErrorCode.POLICY_DENIED, "Office execution requires an approved queue claim")
    record = store.get_pending(approval_id)
    if (
        record is None
        or record.get("status") != "executing"
        or record.get("category") != "office_job"
        or record.get("payload") != payload
    ):
        raise _error(DocumentErrorCode.POLICY_DENIED, "Office approval authority is not executing this payload")
    job_id = _text(payload.get("job_id"), "job_id")
    approved_digest = _text(payload.get("proposal_digest"), "proposal_digest")
    approved_source = _text(payload.get("source_sha256"), "source_sha256")
    actor = _text(payload.get("actor"), "actor")
    destination = Path(_text(payload.get("destination"), "destination"))
    allowlist_root = Path(_text(payload.get("allowlist_root"), "allowlist_root"))
    overwrite = payload.get("overwrite_approved", False)
    if not isinstance(overwrite, bool):
        raise _error(DocumentErrorCode.POLICY_DENIED, "overwrite approval must be boolean")
    home = config.birkin_home()
    service = DocumentService(home)
    runner = DocumentServiceRunner(service, export_root=allowlist_root)
    job = _journal(home).restore(job_id, runner=runner)
    snapshot = job.to_dict()
    if job.state is not OfficeJobState.approval_requested:
        raise _error(DocumentErrorCode.POLICY_DENIED, "Office job is not awaiting approval")
    if _proposal_digest(snapshot) != approved_digest:
        raise _error(DocumentErrorCode.POLICY_DENIED, "approved Office proposal digest changed")
    preview = _mapping(snapshot.get("preview"), "preview")
    if preview.get("source_sha256") != approved_source:
        raise _error(DocumentErrorCode.POLICY_DENIED, "approved Office source digest changed")
    source = _mapping(snapshot.get("source"), "source")
    current = service.inspect_document(source)
    identity = _mapping(current.get("source"), "inspection source")
    if identity.get("sha256") != approved_source:
        raise _error(DocumentErrorCode.POLICY_DENIED, "Office source changed after approval request")
    job.approve(actor=actor)
    _ = job.execute()
    validation = job.validate()
    if validation.get("valid") is not True:
        raise _error(DocumentErrorCode.VALIDATION_FAILED, "executed Office draft failed validation")
    format_name = _text(snapshot.get("format_name"), "format_name")
    _ = job.publish(output_name=f"{job_id}.validated.{format_name}")
    _ = job.export(
        ExportRequest(
            destination=destination,
            actor=actor,
            proposal_digest=approved_digest,
            operations=_job_operations(snapshot),
            overwrite_approved=overwrite,
        )
    )
    return canonical_json(job.receipt())


__all__ = [
    "OfficeCaller",
    "OfficeCoordinator",
    "OfficeMutationRequest",
    "execute_approved_office_job",
]
