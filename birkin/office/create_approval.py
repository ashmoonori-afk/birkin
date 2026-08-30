"""Prepare approval authority for brand-new DOCX documents."""

from __future__ import annotations

import uuid
from typing import final

from .coordinator_data import canonical_office_home
from .create_contract import (
    FORMAT,
    VERSION,
    OfficeCreationCaller,
    OfficeCreationRequest,
    content_sha256,
    creation_content,
    creation_error,
    creation_operations,
    parse_paragraphs,
)
from .create_journal import CreationJobJournal
from .export_types import ExportRequest
from .proposal_integrity import authority_digest, proposal_digest
from .retention import purge_expired_office_state
from .service_workspace import DocumentWorkspace
from .skill_router import route_office_request


@final
class OfficeCreationCoordinator:
    """Build one immutable approval payload without writing a document."""

    def __init__(self, caller: OfficeCreationCaller) -> None:
        self._caller = caller
        self._home = canonical_office_home()
        _ = purge_expired_office_state(self._home)

    def request(self, request: OfficeCreationRequest) -> dict[str, object]:
        route = route_office_request(
            request.request_text,
            artifact_names=(request.destination.name,),
        )
        if route is not None and route.clarification_question is not None:
            raise creation_error(route.clarification_question)
        if route is None or route.conflict or route.format_name != FORMAT:
            raise creation_error(
                "creation request must resolve to exactly one DOCX document"
            )
        paragraphs = parse_paragraphs(request.paragraphs)
        content = creation_content(paragraphs)
        approved_content_sha256 = content_sha256(content)
        job_id = uuid.uuid4().hex
        operations = creation_operations(approved_content_sha256, job_id)
        digest = proposal_digest(
            operations,
            approved_content_sha256,
            request.outcome,
        )
        workspace = DocumentWorkspace(self._home)
        destination = workspace.export_policy(
            self._caller.allowlist_root
        ).resolve_destination(request.destination)
        export = ExportRequest(
            destination=destination,
            actor=self._caller.actor,
            proposal_digest=digest,
            operations=operations,
            overwrite_approved=request.overwrite_approved,
            authority_source_sha256=approved_content_sha256,
        )
        payload: dict[str, object] = {
            "version": VERSION,
            "job_id": job_id,
            "creation_digest": digest,
            "format": FORMAT,
            "content": content,
            "content_sha256": approved_content_sha256,
            "outcome": request.outcome,
            "destination": str(destination),
            "allowlist_root": str(self._caller.allowlist_root.resolve(strict=True)),
            "proposer": self._caller.actor,
            "overwrite_approved": request.overwrite_approved,
            "authority_digest": authority_digest(
                destination,
                approved_content_sha256,
                export,
            ),
            "output_name": f"create-{digest[:32]}.docx",
        }
        CreationJobJournal(workspace.home).create(payload)
        return payload


__all__ = [
    "OfficeCreationCaller",
    "OfficeCreationCoordinator",
    "OfficeCreationRequest",
]
