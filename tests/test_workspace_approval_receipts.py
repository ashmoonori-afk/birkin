from __future__ import annotations

import json

import pytest

from birkin.workspace.approval_receipts import OfficeReceiptProjection


def test_office_receipt_projects_tool_approval_without_diff_identity() -> None:
    # Given
    approval = {
        "category": "office_job",
        "payload": {"job_id": "job-tool-path"},
    }
    receipt = json.dumps(
        {
            "publication": {"artifact": {"artifact_id": "artifact-tool-path"}},
            "validation": {
                "valid": True,
                "layers": {"fidelity": {"status": "not-run"}},
            },
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
    assert projected is not None
    assert projected.diff_id is None
    assert "diff_id" not in projected.event_payload()


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
    assert ("diff_id" in payload) is ("diff_id" in approval_fields)


@pytest.mark.parametrize("diff_id", ["", 7, [], {}])
def test_office_receipt_rejects_malformed_optional_diff_identity(
    diff_id: object,
) -> None:
    receipt = json.dumps({
        "publication": {"artifact": {"artifact_id": "artifact-1"}},
        "validation": {"valid": True, "layers": {"fidelity": {}}},
        "export": {
            "path": "/tmp/export.docx",
            "issued_at": "2026-09-05T00:00:00Z",
            "expires_at": "2026-10-05T00:00:00Z",
        },
    })

    with pytest.raises(ValueError, match="diff_id"):
        OfficeReceiptProjection.from_result(
            "approval-1",
            {"category": "office_job",
             "payload": {"job_id": "job-1", "diff_id": diff_id}},
            receipt,
        )
