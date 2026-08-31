"""Create exact follow-up approvals for Office overwrite collisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from .. import store
from .coordinator import OfficeCaller, OfficeCoordinator, OfficeMutationRequest
from .coordinator_data import (
    canonical_office_home,
    coordinator_error,
    job_journal,
    job_operations,
    required_mapping,
    required_text,
)
from .create_approval import OfficeCreationCoordinator
from .create_contract import (
    OfficeCreationCaller,
    OfficeCreationRequest,
    creation_error,
    parse_paragraphs,
)
from .errors import DocumentErrorCode

OVERWRITE_QUESTION = "기존 파일을 덮어쓸까요?"


def _creation_payload(payload: Mapping[str, object]) -> dict[str, object]:
    content = required_mapping(payload.get("content"), "creation content")
    raw_paragraphs = content.get("paragraphs")
    if not isinstance(raw_paragraphs, Sequence) or isinstance(
        raw_paragraphs,
        (str, bytes),
    ):
        raise creation_error("creation paragraphs are unavailable")
    paragraphs = parse_paragraphs(cast("Sequence[object]", raw_paragraphs))
    destination = Path(required_text(payload.get("destination"), "destination"))
    return OfficeCreationCoordinator(
        OfficeCreationCaller(
            allowlist_root=Path(
                required_text(payload.get("allowlist_root"), "allowlist_root")
            ),
            actor=required_text(payload.get("proposer"), "proposer"),
        )
    ).request(
        OfficeCreationRequest(
            request_text=f"Create a new DOCX document at {destination.name}",
            paragraphs=paragraphs,
            outcome=required_text(payload.get("outcome"), "outcome"),
            destination=destination,
            overwrite_approved=True,
        )
    )


def _mutation_payload(payload: Mapping[str, object]) -> dict[str, object]:
    original_digest = required_text(
        payload.get("proposal_digest"),
        "proposal_digest",
    )
    snapshot = job_journal(canonical_office_home()).latest(
        required_text(payload.get("job_id"), "job_id")
    )
    format_name = required_text(snapshot.get("format_name"), "format_name")
    rebound = OfficeCoordinator(
        OfficeCaller(
            allowlist_root=Path(
                required_text(payload.get("allowlist_root"), "allowlist_root")
            ),
            actor=required_text(payload.get("proposer"), "proposer"),
        )
    ).request(
        OfficeMutationRequest(
            request_text=f"Update this {format_name.upper()} document",
            source=required_mapping(snapshot.get("source"), "source"),
            outcome=required_text(snapshot.get("outcome"), "outcome"),
            operations=tuple(job_operations(snapshot)),
            destination=Path(required_text(payload.get("destination"), "destination")),
            overwrite_approved=True,
        )
    )
    if rebound.get("proposal_digest") != original_digest:
        raise coordinator_error(
            DocumentErrorCode.POLICY_DENIED,
            "overwrite follow-up changed the approved Office proposal",
        )
    return rebound


def queue_overwrite_follow_up(
    *,
    approval_id: str,
    category: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    """Queue one explicit overwrite approval with freshly bound authority."""
    if payload.get("overwrite_approved") is not False:
        raise coordinator_error(
            DocumentErrorCode.POLICY_DENIED,
            "overwrite follow-up requires an unapproved collision",
        )
    match category:
        case "office_create":
            rebound = _creation_payload(payload)
        case "office_job":
            rebound = _mutation_payload(payload)
        case _:
            raise coordinator_error(
                DocumentErrorCode.POLICY_DENIED,
                "Office category does not support overwrite follow-up",
            )
    origin = f"overwrite-retry:{approval_id}"
    existing = next(
        (
            record
            for record in store.list_pending()
            if record.get("origin") == origin and record.get("category") == category
        ),
        None,
    )
    if existing is not None:
        return {
            "auto": False,
            "id": str(existing["id"]),
            "title": OVERWRITE_QUESTION,
        }
    queued = store.add_pending(
        category=category,
        title=OVERWRITE_QUESTION,
        description=(
            f"{required_text(rebound.get('destination'), 'destination')}에 "
            "기존 파일이 있습니다. 승인하면 정확히 같은 작업으로 교체합니다."
        ),
        payload=rebound,
        origin=origin,
        details={
            "retry_of_approval_id": approval_id,
            "overwrite_retry": True,
        },
    )
    return {
        "auto": False,
        "id": str(queued["id"]),
        "title": OVERWRITE_QUESTION,
    }


__all__ = ["OVERWRITE_QUESTION", "queue_overwrite_follow_up"]
