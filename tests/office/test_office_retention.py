from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from birkin import store
from birkin.office.errors import DocumentError
from birkin.office.export_policy import ExportRequest
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.retention import purge_expired_office_state
from birkin.office.service import DocumentService
from birkin.office.service_types import ArtifactRef
from birkin.office.service_workspace import DocumentWorkspace


def _validated_draft(service: DocumentService) -> ArtifactRef:
    workspace = DocumentWorkspace(service.home)
    output = workspace.output_path("validated.txt", ".txt")

    def write(target: Path) -> None:
        _ = target.write_text("retained export", encoding="utf-8")

    _ = workspace.atomic_publish(output, write)
    return workspace.artifact(output)


def _request(destination: Path) -> ExportRequest:
    return ExportRequest(
        destination=destination,
        actor="tester",
        proposal_digest="proposal",
        operations=({"op": "replace", "value": "retained export"},),
        overwrite_approved=True,
    )


def test_expired_receipt_purges_backup_and_journals(
    tmp_path: Path,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    _ = destination.write_text("original bytes", encoding="utf-8")
    receipt = DocumentServiceRunner(
        service,
        export_root=caller,
    ).export(
        artifact=_validated_draft(service),
        request=_request(destination),
    )
    jobs = service.home / "jobs"
    jobs.mkdir()
    job_path = jobs / f"{'a' * 32}.jsonl"
    _ = job_path.write_text(
        json.dumps(
            {
                "job_id": "a" * 32,
                "state": "exported",
                "export": receipt,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    backup = service.home / "artifacts" / "export-backups" / (
        f"{receipt['rollback_token']}.bak"
    )
    transaction = next(
        (service.home / "artifacts" / "export-journal").glob("*.json")
    )
    expires = datetime.fromisoformat(
        str(receipt["expires_at"]).replace("Z", "+00:00")
    )

    retained = purge_expired_office_state(
        service.home,
        now=expires - timedelta(seconds=1),
    )
    with store.file_lock(job_path):
        locked = purge_expired_office_state(
            service.home,
            now=expires + timedelta(seconds=1),
        )
        assert backup.exists()
        assert transaction.exists()
        assert job_path.exists()
    purged = purge_expired_office_state(
        service.home,
        now=expires + timedelta(seconds=1),
    )
    repeated = purge_expired_office_state(
        service.home,
        now=expires + timedelta(seconds=1),
    )

    assert retained == {"jobs": 0, "backups": 0, "transactions": 0}
    assert locked == {"jobs": 0, "backups": 0, "transactions": 0}
    assert purged == {"jobs": 1, "backups": 1, "transactions": 1}
    assert repeated == {"jobs": 0, "backups": 0, "transactions": 0}
    assert not backup.exists()
    assert not transaction.exists()
    assert not job_path.exists()
    assert destination.read_text(encoding="utf-8") == "retained export"


def test_purge_rejects_transaction_selected_cross_backup(
    tmp_path: Path,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    runner = DocumentServiceRunner(service, export_root=caller)
    artifact = _validated_draft(service)
    receipts: list[dict[str, object]] = []
    for name in ("a", "b"):
        destination = caller / f"{name}.txt"
        _ = destination.write_text(f"{name} original", encoding="utf-8")
        receipts.append(
            dict(
                runner.export(
                    artifact=artifact,
                    request=_request(destination),
                )
            )
        )
    first, second = receipts
    jobs = service.home / "jobs"
    jobs.mkdir()
    job_path = jobs / f"{'a' * 32}.jsonl"
    _ = job_path.write_text(
        json.dumps(
            {
                "job_id": "a" * 32,
                "state": "exported",
                "export": first,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    transactions = service.home / "artifacts" / "export-journal"
    first_transaction = next(
        path
        for path in transactions.glob("*.json")
        if json.loads(path.read_text(encoding="utf-8"))["rollback_token"]
        == first["rollback_token"]
    )
    record = json.loads(first_transaction.read_text(encoding="utf-8"))
    second_backup = service.home / "artifacts" / "export-backups" / (
        f"{second['rollback_token']}.bak"
    )
    first_backup = service.home / "artifacts" / "export-backups" / (
        f"{first['rollback_token']}.bak"
    )
    record["backup"] = str(second_backup)
    first_transaction.write_text(json.dumps(record), encoding="utf-8")
    expires = datetime.fromisoformat(
        str(first["expires_at"]).replace("Z", "+00:00")
    )

    with pytest.raises(DocumentError, match="backup path"):
        _ = purge_expired_office_state(
            service.home,
            now=expires + timedelta(seconds=1),
        )

    assert first_backup.exists()
    assert second_backup.exists()
