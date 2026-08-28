from __future__ import annotations

from pathlib import Path

import pytest

from birkin.office.errors import DocumentError
from birkin.office.export_policy import ExportRequest
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.service import DocumentService
from birkin.office.service_workspace import DocumentWorkspace


def test_signed_receipt_cannot_downgrade_to_legacy(
    tmp_path: Path,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    workspace = DocumentWorkspace(service.home)
    draft = workspace.output_path("validated.txt", ".txt")

    def write(target: Path) -> None:
        _ = target.write_text("validated export", encoding="utf-8")

    _ = workspace.atomic_publish(draft, write)
    artifact = workspace.artifact(draft)
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    _ = destination.write_text("original bytes", encoding="utf-8")
    receipt = DocumentServiceRunner(
        service,
        export_root=caller,
    ).export(
        artifact=artifact,
        request=ExportRequest(
            destination=destination,
            actor="tester",
            proposal_digest="proposal",
            operations=({"op": "replace", "value": "validated export"},),
            overwrite_approved=True,
        ),
    )
    downgraded = dict(receipt)
    for field in ("receipt_hmac", "issued_at", "expires_at"):
        del downgraded[field]

    with pytest.raises(DocumentError, match="legacy unsigned rollback"):
        _ = DocumentServiceRunner(
            service,
            export_root=caller,
        ).rollback_export(downgraded)

    assert destination.read_text(encoding="utf-8") == "validated export"
