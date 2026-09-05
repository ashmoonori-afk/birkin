from __future__ import annotations

import json

import pytest

from birkin.workspace.approval_receipts import OfficeReceiptProjection


def test_office_receipt_projection_skips_tool_approval_without_diff_identity() -> None:
    # Given
    approval = {
        "category": "office_job",
        "payload": {"job_id": "job-tool-path"},
    }
    receipt = json.dumps(
        {
            "publication": {"artifact": {"artifact_id": "artifact-tool-path"}},
            "export": {
                "path": "/tmp/export.docx",
                "issued_at": "2026-08-29T22:00:00Z",
                "expires_at": "2026-09-28T22:00:00Z",
            },
        }
    )

    # When
    projected = OfficeReceiptProjection.from_result(
        "approval-tool-path",
        approval,
        receipt,
    )

    # Then
    assert projected is None


@pytest.mark.parametrize(
    ("category", "approval_fields", "artifact_container"),
    [
        (
            "office_job",
            {"job_id": "job-1", "diff_id": "diff-1"},
            "publication",
        ),
        ("office_create", {"job_id": "job-2"}, "creation"),
    ],
)
def test_office_receipt_projects_result_and_validation_limits(
    category: str,
    approval_fields: dict[str, str],
    artifact_container: str,
) -> None:
    receipt = {
        artifact_container: {"artifact": {"artifact_id": "artifact-1"}},
        "validation": {
            "valid": True,
            "layers": {"fidelity": {"status": "not-run"}},
        },
        "export": {
            "path": "/tmp/export.docx",
            "issued_at": "2026-09-05T00:00:00Z",
            "expires_at": "2026-10-05T00:00:00Z",
            "destination_existed": False,
        },
    }

    projected = OfficeReceiptProjection.from_result(
        "approval-1",
        {"category": category, "payload": approval_fields},
        json.dumps(receipt),
    )

    assert projected is not None
    payload = projected.event_payload()
    assert payload["artifact_id"] == "artifact-1"
    assert payload["validation_summary"] == "등록된 구조 검증 통과"
    assert payload["visual_validation_summary"] == "시각 검증 미실행"
    assert ("diff_id" in payload) is (category == "office_job")
