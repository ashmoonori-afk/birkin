"""Project approved Office exports into workspace receipt events."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from typing import cast


_OFFICE_RECEIPT_PREFIX = "office:"


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"Office receipt {field} must be an object")
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        raise ValueError(f"Office receipt {field} must be an object")
    return cast(dict[str, object], raw)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Office receipt {field} must be non-empty")
    return value


@dataclass(frozen=True, slots=True)
class OfficeReceiptProjection:
    approval_id: str
    artifact_id: str
    diff_id: str
    job_id: str
    destination: str
    receipt_ref: str
    issued_at: str
    expires_at: str
    backup_exists: bool

    @classmethod
    def from_result(
        cls,
        approval_id: str,
        approval_record: Mapping[str, object],
        receipt_text: str,
    ) -> OfficeReceiptProjection | None:
        if approval_record.get("category") != "office_job":
            return None
        approval = _mapping(approval_record.get("payload"), "approval")
        decoded = cast(object, json.loads(receipt_text))
        receipt = _mapping(decoded, "root")
        publication = _mapping(receipt.get("publication"), "publication")
        artifact = _mapping(publication.get("artifact"), "artifact")
        export = _mapping(receipt.get("export"), "export")
        job_id = _text(approval.get("job_id"), "job_id")
        return cls(
            approval_id=approval_id,
            artifact_id=_text(artifact.get("artifact_id"), "artifact_id"),
            diff_id=_text(approval.get("diff_id"), "diff_id"),
            job_id=job_id,
            destination=_text(export.get("path"), "destination"),
            receipt_ref=f"{_OFFICE_RECEIPT_PREFIX}{job_id}",
            issued_at=_text(export.get("issued_at"), "issued_at"),
            expires_at=_text(export.get("expires_at"), "expires_at"),
            backup_exists=export.get("destination_existed") is True,
        )

    def event_payload(self) -> dict[str, object]:
        return {
            "summary": "Office export completed",
            "approval_id": self.approval_id,
            "artifact_id": self.artifact_id,
            "diff_id": self.diff_id,
            "job_id": self.job_id,
            "destination": self.destination,
            "receipt_ref": self.receipt_ref,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "backup_exists": self.backup_exists,
        }


def job_id_from_receipt_ref(receipt_ref: str) -> str:
    if not receipt_ref.startswith(_OFFICE_RECEIPT_PREFIX):
        raise ValueError("receipt_ref does not identify an Office export")
    job_id = receipt_ref.removeprefix(_OFFICE_RECEIPT_PREFIX)
    if not job_id:
        raise ValueError("receipt_ref does not identify an Office export")
    return job_id


def approval_turn_context(
    approval_id: str,
    outcome: str,
    receipt: OfficeReceiptProjection | None,
    error: str | None = None,
) -> str:
    if outcome == "approved":
        summary = "승인된 작업이 완료되었습니다."
        if receipt is not None:
            summary += f" 저장 위치: {receipt.destination}"
    elif outcome == "rejected":
        summary = "승인 요청이 거부되어 작업을 실행하지 않았습니다."
    else:
        summary = "승인된 작업을 완료하지 못했습니다."
        if error:
            summary += f" 원인: {error[:240]}"
    return (
        f'<approval-outcome lang="ko" '
        f'approval_id="{escape(approval_id, quote=True)}" '
        f'outcome="{escape(outcome, quote=True)}">'
        f"{escape(summary)}</approval-outcome>"
    )
