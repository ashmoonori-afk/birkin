"""Regression cover for Office creation, coordinator, and retention hardening."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from birkin.office.coordinator import _semantic_summaries
from birkin.office.create_approval import OfficeCreationCoordinator
from birkin.office.create_contract import (
    OfficeCreationCaller,
    OfficeCreationRequest,
    parse_paragraphs,
)
from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.export_policy import ExportRequest
from birkin.office.extract_contract import MAX_TEXT_BYTES
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.overwrite_retry import queue_overwrite_follow_up
from birkin.office.retention import purge_expired_office_state
from birkin.office.service import DocumentService
from birkin.office.service_types import ArtifactRef
from birkin.office.service_workspace import DocumentWorkspace

_JOB_ID = "b" * 32
_CREATION_JOB_ID = "c" * 32


def _caller_root(tmp_path: Path) -> Path:
    caller = tmp_path / "caller"
    caller.mkdir(exist_ok=True)
    return caller


@pytest.mark.parametrize(
    "name",
    ["notes.xlsx.docx", "hwp-notes.docx", "excel-summary.docx"],
)
def test_overwrite_retry_routes_docx_for_confusable_destination_names(
    tmp_path: Path,
    name: str,
) -> None:
    # Given: an approved DOCX creation whose filename mentions another format.
    caller = _caller_root(tmp_path)
    payload = {
        "content": {"paragraphs": ["첫 문단"]},
        "destination": str(caller / name),
        "allowlist_root": str(caller),
        "proposer": "tester",
        "outcome": "새 보고서",
        "overwrite_approved": False,
    }

    # When: the overwrite collision is re-queued for explicit approval.
    queued = queue_overwrite_follow_up(
        approval_id="approval-1",
        category="office_create",
        payload=payload,
    )

    # Then: the retry still routes to DOCX instead of a format conflict.
    assert queued["auto"] is False


def test_parse_paragraphs_rejects_control_characters() -> None:
    # Given: a paragraph carrying a newline that DOCX extraction would drop.
    with pytest.raises(DocumentError) as raised:
        _ = parse_paragraphs(["첫 줄\n둘째 줄"])

    # Then: the approval boundary refuses it as invalid input.
    assert raised.value.code is DocumentErrorCode.INVALID_INPUT
    assert "제어 문자" in str(raised.value)


def test_parse_paragraphs_rejects_text_over_the_extraction_byte_limit() -> None:
    # Given: Korean paragraphs whose UTF-8 size exceeds the extraction limit.
    paragraphs = ["한" * 60_000] * 6
    assert sum(len(item.encode("utf-8")) for item in paragraphs) > MAX_TEXT_BYTES

    with pytest.raises(DocumentError) as raised:
        _ = parse_paragraphs(paragraphs)

    assert raised.value.code is DocumentErrorCode.INVALID_INPUT


def test_creation_request_rejects_oversized_plan_before_journaling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a creation request with more paragraphs than the plan allows.
    home = tmp_path / "home"
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    caller = _caller_root(tmp_path)
    coordinator = OfficeCreationCoordinator(
        OfficeCreationCaller(allowlist_root=caller, actor="tester")
    )

    # When: the request is made.
    with pytest.raises(DocumentError) as raised:
        _ = coordinator.request(
            OfficeCreationRequest(
                request_text="Create a new DOCX document",
                paragraphs=tuple("문단" for _ in range(10_001)),
                outcome="새 보고서",
                destination=caller / "report.docx",
            )
        )

    # Then: it fails at request time and no creation job is journaled.
    assert raised.value.code is DocumentErrorCode.INVALID_INPUT
    creation_jobs = home / "office" / "creation-jobs"
    assert not creation_jobs.exists() or not list(creation_jobs.glob("*.json"))


def test_semantic_summary_accepts_title_placeholder_and_empty_value() -> None:
    # Given: a single-node preview and an operation on placeholder index 0.
    preview = {
        "preview": {
            "nodes": [
                {
                    "source_locator": {"format": "pptx", "index": 1},
                    "kind": "placeholder",
                    "text": "Old title",
                }
            ]
        }
    }

    summaries = _semantic_summaries(preview, ({"placeholder_idx": 0, "value": ""},))

    # Then: index 0 is a real location and the cleared value survives.
    assert summaries == [{"location": "0", "before": "Old title", "after": ""}]


def test_semantic_summary_rejects_an_operation_without_a_location() -> None:
    preview = {
        "preview": {
            "nodes": [
                {
                    "source_locator": {"format": "pptx", "index": 1},
                    "kind": "placeholder",
                    "text": "Old title",
                }
            ]
        }
    }

    with pytest.raises(DocumentError) as raised:
        _ = _semantic_summaries(preview, ({"value": "New title"},))

    assert raised.value.code is DocumentErrorCode.INVALID_INPUT


def _write_job_journal(jobs: Path, job_id: str, record: dict[str, object]) -> Path:
    jobs.mkdir(parents=True, exist_ok=True)
    path = jobs / f"{job_id}.jsonl"
    _ = path.write_text(
        json.dumps(record, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _age(path: Path, days: int) -> datetime:
    stamp = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    os.utime(path, (stamp, stamp))
    return datetime.fromtimestamp(stamp, timezone.utc)


def _seed_draft(office_home: Path, name: str) -> tuple[Path, Path]:
    drafts = office_home / "artifacts" / "drafts"
    intents = office_home / "artifacts" / "execution-journal"
    drafts.mkdir(parents=True, exist_ok=True)
    intents.mkdir(parents=True, exist_ok=True)
    draft = drafts / name
    _ = draft.write_bytes(b"draft bytes")
    intent = intents / f"{hashlib.sha256(name.encode('utf-8')).hexdigest()}.json"
    _ = intent.write_text("{}", encoding="utf-8")
    return draft, intent


def test_abandoned_job_expires_with_its_draft_and_execution_intent(
    tmp_path: Path,
) -> None:
    # Given: a job abandoned before approval, older than the retention window.
    office_home = tmp_path / "office-home"
    path = _write_job_journal(
        office_home / "jobs",
        _JOB_ID,
        {"job_id": _JOB_ID, "state": "approved", "format_name": "docx"},
    )
    draft, intent = _seed_draft(office_home, f"{_JOB_ID}.draft.docx")
    mtime = _age(path, 40)

    # When: retention runs before and after the job's expiry.
    retained = purge_expired_office_state(
        office_home,
        now=mtime + timedelta(days=29),
    )
    purged = purge_expired_office_state(
        office_home,
        now=mtime + timedelta(days=31),
    )

    # Then: only the expired run removes the journal, draft, and intent.
    assert retained == {"jobs": 0, "backups": 0, "transactions": 0}
    assert purged == {"jobs": 1, "backups": 0, "transactions": 0}
    assert not path.exists()
    assert not draft.exists()
    assert not intent.exists()


def _validated_draft(service: DocumentService) -> ArtifactRef:
    workspace = DocumentWorkspace(service.home)
    output = workspace.output_path("validated.txt", ".txt")

    def write(target: Path) -> None:
        _ = target.write_text("retained export", encoding="utf-8")

    _ = workspace.atomic_publish(output, write)
    return workspace.artifact(output)


def test_terminal_creation_job_purges_backup_transaction_and_draft(
    tmp_path: Path,
) -> None:
    # Given: an exported creation job with a real export receipt and draft.
    service = DocumentService(tmp_path / "office-home")
    caller = _caller_root(tmp_path)
    destination = caller / "result.txt"
    _ = destination.write_text("original bytes", encoding="utf-8")
    receipt = DocumentServiceRunner(service, export_root=caller).export(
        artifact=_validated_draft(service),
        request=ExportRequest(
            destination=destination,
            actor="tester",
            proposal_digest="proposal",
            operations=({"op": "replace", "value": "retained export"},),
            overwrite_approved=True,
        ),
    )
    output_name = "create-" + "d" * 32 + ".docx"
    draft, intent = _seed_draft(service.home, output_name)
    creation_jobs = service.home / "creation-jobs"
    creation_jobs.mkdir(parents=True)
    record = creation_jobs / f"{_CREATION_JOB_ID}.json"
    _ = record.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "office_create",
                "job_id": _CREATION_JOB_ID,
                "state": "exported",
                "approval": {"output_name": output_name},
                "export": receipt,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    backup = (
        service.home / "artifacts" / "export-backups"
        / f"{receipt['rollback_token']}.bak"
    )
    transaction = next((service.home / "artifacts" / "export-journal").glob("*.json"))
    expires = datetime.fromisoformat(
        str(receipt["expires_at"]).replace("Z", "+00:00")
    )

    # When: retention runs before and after the receipt expires.
    retained = purge_expired_office_state(
        service.home,
        now=expires - timedelta(seconds=1),
    )
    purged = purge_expired_office_state(
        service.home,
        now=expires + timedelta(seconds=1),
    )

    # Then: the creation record, its backup, transaction, and draft all go.
    assert retained == {"jobs": 0, "backups": 0, "transactions": 0}
    assert purged == {"jobs": 1, "backups": 1, "transactions": 1}
    assert not record.exists()
    assert not backup.exists()
    assert not transaction.exists()
    assert not draft.exists()
    assert not intent.exists()


def test_unapproved_creation_job_expires_with_its_managed_draft(
    tmp_path: Path,
) -> None:
    # Given: a creation approval nobody ever acted on, past the retention window.
    office_home = tmp_path / "office-home"
    creation_jobs = office_home / "creation-jobs"
    creation_jobs.mkdir(parents=True)
    output_name = "create-" + "e" * 32 + ".docx"
    draft, intent = _seed_draft(office_home, output_name)
    record = creation_jobs / f"{_CREATION_JOB_ID}.json"
    _ = record.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "office_create",
                "job_id": _CREATION_JOB_ID,
                "state": "approval_requested",
                "approval": {"output_name": output_name},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    mtime = _age(record, 40)

    # When: retention runs before and after the job expires.
    retained = purge_expired_office_state(
        office_home,
        now=mtime + timedelta(days=29),
    )
    purged = purge_expired_office_state(
        office_home,
        now=mtime + timedelta(days=31),
    )

    # Then: the stale creation job and its draft stop accumulating.
    assert retained == {"jobs": 0, "backups": 0, "transactions": 0}
    assert purged == {"jobs": 1, "backups": 0, "transactions": 0}
    assert not record.exists()
    assert not draft.exists()
    assert not intent.exists()
