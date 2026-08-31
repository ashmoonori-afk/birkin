"""Execute one exact approval-bound DOCX creation proposal."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from .. import store
from .artifact_serialization import canonical_integrity_json
from .coordinator_data import canonical_office_home
from .create_contract import (
    CATEGORY,
    FORMAT,
    PAYLOAD_KEYS,
    VERSION,
    content_sha256,
    creation_content,
    creation_error,
    creation_operations,
    parse_paragraphs,
    required_text,
)
from .create_journal import CreationJobJournal
from .errors import DocumentError, DocumentErrorCode
from .export_types import ExportRequest, JSONValue
from .proposal_integrity import authority_digest, proposal_digest
from .service import DocumentService
from .service_types import ArtifactRef
from .service_workspace import DocumentWorkspace


def _approval_authorized(
    payload: Mapping[str, object],
    approval_id: str | None,
) -> None:
    if approval_id is None:
        raise creation_error("creation execution requires approval queue authority")
    record = store.get_pending(approval_id)
    if (
        record is None
        or record.get("category") != CATEGORY
        or record.get("status") != "executing"
        or record.get("approved_by") is None
        or record.get("approved_via") is None
        or record.get("payload") != dict(payload)
    ):
        raise creation_error("creation execution is not bound to an active approval")


def _parsed_payload(
    payload: Mapping[str, object],
) -> tuple[
    dict[str, JSONValue],
    tuple[str, ...],
    str,
    Path,
    Path,
    ExportRequest,
    str,
]:
    if set(payload) != PAYLOAD_KEYS:
        raise creation_error("creation approval payload fields changed")
    if payload.get("version") != VERSION or payload.get("format") != FORMAT:
        raise creation_error("creation approval version or format changed")
    raw_content = payload.get("content")
    if not isinstance(raw_content, Mapping) or set(raw_content) != {"paragraphs"}:
        raise creation_error("creation content fields changed")
    paragraphs = parse_paragraphs(raw_content.get("paragraphs"))
    content = creation_content(paragraphs)
    approved_content_sha256 = required_text(
        payload.get("content_sha256"),
        "content_sha256",
    )
    if approved_content_sha256 != content_sha256(content):
        raise creation_error("creation content changed after approval")
    outcome = required_text(payload.get("outcome"), "outcome")
    job_id = required_text(payload.get("job_id"), "job_id")
    operations = creation_operations(approved_content_sha256, job_id)
    digest = proposal_digest(operations, approved_content_sha256, outcome)
    if digest != required_text(payload.get("creation_digest"), "creation_digest"):
        raise creation_error("creation proposal changed after approval")
    output_name = required_text(payload.get("output_name"), "output_name")
    if output_name != f"create-{digest[:32]}.docx":
        raise creation_error("creation output identity changed after approval")
    destination = Path(required_text(payload.get("destination"), "destination"))
    allowlist_root = Path(
        required_text(payload.get("allowlist_root"), "allowlist_root")
    )
    proposer = required_text(payload.get("proposer"), "proposer")
    overwrite_approved = payload.get("overwrite_approved")
    if not isinstance(overwrite_approved, bool):
        raise creation_error("overwrite_approved must be a boolean")
    request = ExportRequest(
        destination=destination,
        actor=proposer,
        proposal_digest=digest,
        operations=operations,
        overwrite_approved=overwrite_approved,
        authority_digest=required_text(
            payload.get("authority_digest"),
            "authority_digest",
        ),
        authority_source_sha256=approved_content_sha256,
    )
    expected_authority = authority_digest(
        destination,
        approved_content_sha256,
        request,
    )
    if request.authority_digest != expected_authority:
        raise creation_error("creation export authority changed after approval")
    return (
        content,
        paragraphs,
        output_name,
        destination,
        allowlist_root,
        request,
        approved_content_sha256,
    )


def execute_approved_office_creation(
    payload: Mapping[str, object],
    *,
    approval_id: str | None,
) -> str:
    """Create, validate, and export the exact approved DOCX proposal."""
    _approval_authorized(payload, approval_id)
    (
        content,
        paragraphs,
        output_name,
        destination,
        allowlist_root,
        export_request,
        approved_content_sha256,
    ) = _parsed_payload(payload)
    service = DocumentService(canonical_office_home())
    workspace = DocumentWorkspace(service.home)
    journal = CreationJobJournal(service.home)
    _ = journal.require_approval(payload)
    resolved = workspace.export_policy(allowlist_root).resolve_destination(destination)
    if resolved != destination:
        raise creation_error("creation destination changed after approval")
    draft = workspace.drafts / output_name
    if draft.exists() or draft.is_symlink():
        artifact = workspace.artifact(
            draft,
            {"sensitivity": "internal"},
        )
    else:
        created = service.create_document(
            format=FORMAT,
            content=content,
            output_name=output_name,
        )
        artifact = cast("ArtifactRef", created["draft_artifact"])
    extracted = service.extract_document(
        artifact,
        max_spans=max(1, len(paragraphs)),
        max_nodes=max(1, len(paragraphs)),
        max_text_bytes=1_000_000,
    )
    if extracted["truncation"]["truncated"] or extracted["text"] != "\n".join(
        paragraphs
    ):
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "office_create",
            "managed creation draft does not match the approved content",
        )
    validation = service.validate_artifact(artifact)
    if validation["status"] not in {"ok", "warning"}:
        raise creation_error("created DOCX failed validation")
    policy = workspace.export_policy(allowlist_root)
    snapshot = workspace.artifact_snapshot(artifact)
    with snapshot:
        receipt = policy.export(snapshot.path, export_request)
    result = {
        "job_id": required_text(payload.get("job_id"), "job_id"),
        "state": "exported",
        "creation": {
            "format": FORMAT,
            "content_sha256": approved_content_sha256,
            "artifact": artifact,
        },
        "validation": validation,
        "export": receipt.public(),
    }
    journal.mark_exported(payload, result)
    return canonical_integrity_json(result)


def approved_creation_receipt(payload: Mapping[str, object]) -> str:
    job_id = required_text(payload.get("job_id"), "job_id")
    result = CreationJobJournal(canonical_office_home()).latest(job_id).get("result")
    if not isinstance(result, Mapping):
        raise creation_error("durable creation receipt is unavailable")
    return canonical_integrity_json(result)


__all__ = ["approved_creation_receipt", "execute_approved_office_creation"]
