"""Canonical approval coordinator for durable Office document mutations."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import final

from .coordinator_data import (
    canonical_office_home as _office_home,
    coordinator_error as _error,
    job_journal as _journal,
    required_mapping as _mapping,
    required_sequence as _sequence,
    required_text as _text,
)
from .errors import DocumentError, DocumentErrorCode
from .job import OfficeJob
from .job_runner import DocumentServiceRunner
from .preview_semantics import summarize_operations
from .service import DocumentService
from .service_workspace import DocumentWorkspace
from .skill_router import route_office_request


@dataclass(frozen=True, slots=True)
class OfficeCaller:
    """Trusted actor and filesystem policy supplied by ToolContext."""

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


@final
class OfficeCoordinator:
    """Prepare one reviewable Office job without executing its mutation."""

    def __init__(self, caller: OfficeCaller) -> None:
        self._caller = caller
        self._home = _office_home()
        self._service = DocumentService(self._home)

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
        policy = DocumentWorkspace(self._home).export_policy(
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
            journal=_journal(self._home),
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
    """Resume only the exact payload owned by an executing approval record."""
    from .coordinator_recovery import execute_approved_office_job as resume

    return resume(payload, approval_id=approval_id)


__all__ = [
    "OfficeCaller",
    "OfficeCoordinator",
    "OfficeMutationRequest",
    "execute_approved_office_job",
]
