from __future__ import annotations

import json

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
