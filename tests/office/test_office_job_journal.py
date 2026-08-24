from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.export_policy import ExportRequest
from birkin.office.job import OfficeJob, OfficeJobState
from birkin.office.job_journal import OfficeJobJournal


class FakeRunner:
    def __init__(self) -> None:
        self.execute_calls = 0

    def preview(
        self,
        *,
        source: Mapping[str, object],
        format_name: str,
        operations: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        return {"source_sha256": "source-sha", "status": "ready"}

    def execute(
        self,
        *,
        source: Mapping[str, object],
        format_name: str,
        operations: Sequence[Mapping[str, object]],
        draft_name: str,
    ) -> dict[str, object]:
        self.execute_calls += 1
        return {
            "artifact": {"uri": draft_name, "content_hash": "draft-sha"},
            "sha256": "draft-sha",
        }

    def validate(self, *, artifact: Mapping[str, object]) -> dict[str, object]:
        return {"status": "pass", "valid": True}

    def publish(
        self, *, artifact: Mapping[str, object], output_name: str
    ) -> dict[str, object]:
        return {
            "artifact": {"uri": f"drafts/{output_name}", "content_hash": "published-sha"},
            "sha256": "published-sha",
        }

    def export(
        self, *, artifact: Mapping[str, object], request: ExportRequest
    ) -> dict[str, object]:
        return {
            "path": str(request.destination),
            "source_sha256": artifact["content_hash"],
            "output_sha256": artifact["content_hash"],
            "rollback_token": "rollback-1",
        }

    def rollback_export(
        self, receipt: Mapping[str, object]
    ) -> dict[str, object]:
        return {"path": receipt["path"], "restored": False}


def _job(journal: OfficeJobJournal | None = None) -> tuple[OfficeJob, FakeRunner]:
    runner = FakeRunner()
    return (
        OfficeJob(
            job_id="job-1",
            format_name="docx",
            source={"uri": "source.docx", "content_hash": "source-sha"},
            runner=runner,
            journal=journal,
        ),
        runner,
    )


def _advance_to_approved(job: OfficeJob) -> None:
    job.declare_outcome("Replace the heading")
    job.propose_operations([{"type": "replace_text", "value": "New"}])
    job.build_preview()
    _ = job.request_approval()
    job.approve(actor="reviewer")


def _advance_to_validated(job: OfficeJob) -> None:
    _advance_to_approved(job)
    job.execute()
    job.validate()


def _export_request(destination: Path) -> ExportRequest:
    return ExportRequest(
        destination=destination,
        actor="reviewer",
        proposal_digest="proposal-sha",
        operations=({"type": "replace_text", "value": "New"},),
    )


def test_approved_snapshot_roundtrip_preserves_every_serialized_field() -> None:
    # Given: an approved job with proposal-bound approval state.
    job, _runner = _job()
    _advance_to_approved(job)

    # When: the complete snapshot is restored with a new runner.
    snapshot = job.to_dict()
    restored = OfficeJob.from_dict(snapshot, runner=FakeRunner())

    # Then: only the runner is replaced; durable state is exact.
    assert set(snapshot) == {
        "job_id",
        "format_name",
        "source",
        "state",
        "history",
        "outcome",
        "operations",
        "preview",
        "approval",
        "approved_digest",
        "execution",
        "artifact",
        "validation",
        "publication",
        "export",
        "rollback",
        "failure",
    }
    assert restored.to_dict() == snapshot
    assert restored.state is OfficeJobState.approved
    assert restored.history == job.history
    assert restored.to_dict()["approved_digest"] == snapshot["approved_digest"]


def test_restored_approved_job_executes_with_injected_runner(tmp_path: Path) -> None:
    # Given: an approved job durably recorded by its workspace journal.
    journal = OfficeJobJournal(tmp_path)
    job, _runner = _job(journal)
    _advance_to_approved(job)
    resumed_runner = FakeRunner()

    # When: a restarted process restores and executes the approved job.
    restored = journal.restore("job-1", runner=resumed_runner)
    execution = restored.execute()

    # Then: execution resumes from approval and its transition is durable.
    assert execution["sha256"] == "draft-sha"
    assert resumed_runner.execute_calls == 1
    assert journal.restore("job-1", runner=FakeRunner()).state is OfficeJobState.executed


def test_abrupt_process_exit_restores_last_complete_transition(tmp_path: Path) -> None:
    # Given: a child process that exits immediately after a durable transition.
    script = f"""
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from birkin.office.job import OfficeJob
from birkin.office.job_journal import OfficeJobJournal
class Runner:
    def preview(self, *, source: Mapping[str, object], format_name: str, operations: Sequence[Mapping[str, object]]) -> dict[str, object]:
        return {{"source_sha256": "source-sha"}}
    def execute(self, *, source: Mapping[str, object], format_name: str, operations: Sequence[Mapping[str, object]], draft_name: str) -> dict[str, object]:
        return {{}}
    def validate(self, *, artifact: Mapping[str, object]) -> dict[str, object]:
        return {{}}
    def publish(self, *, artifact: Mapping[str, object], output_name: str) -> dict[str, object]:
        return {{}}
journal = OfficeJobJournal(Path({str(tmp_path)!r}))
job = OfficeJob(job_id="crashed", format_name="docx", source={{"uri": "source.docx"}}, runner=Runner(), journal=journal)
job.declare_outcome("Crash-safe outcome")
os._exit(23)
"""

    # When: the process terminates without normal Python cleanup.
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[2],
        env={**os.environ, "PYTHONPATH": "."},
        check=False,
    )

    # Then: the fsynced transition is the exact resume point.
    assert completed.returncode == 23
    restored = OfficeJobJournal(tmp_path).restore("crashed", runner=FakeRunner())
    assert restored.state is OfficeJobState.outcome_declared
    assert restored.history == (
        OfficeJobState.input_captured,
        OfficeJobState.outcome_declared,
    )


def test_every_completed_transition_appends_exactly_one_snapshot(tmp_path: Path) -> None:
    # Given: a journaled job at its initial captured-input transition.
    journal = OfficeJobJournal(tmp_path)
    job, _runner = _job(journal)

    # When: five more transitions complete through approval.
    _advance_to_approved(job)

    # Then: each history entry has one complete JSONL snapshot.
    lines = journal.path_for("job-1").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(job.history) == 6
    assert [json.loads(line)["state"] for line in lines] == [
        state.value for state in job.history
    ]


def test_restore_ignores_only_a_trailing_partial_snapshot(tmp_path: Path) -> None:
    # Given: two complete transitions followed by crash-torn JSON.
    journal = OfficeJobJournal(tmp_path)
    job, _runner = _job(journal)
    job.declare_outcome("Keep the complete state")
    with journal.path_for("job-1").open("ab") as handle:
        _ = handle.write(b'{"job_id":"job-1","state":"operations_proposed"')

    # When: the job is restored.
    restored = journal.restore("job-1", runner=FakeRunner())

    # Then: the last newline-complete snapshot wins.
    assert restored.state is OfficeJobState.outcome_declared
    assert restored.to_dict() == job.to_dict()


def test_restore_rejects_malformed_complete_snapshot(tmp_path: Path) -> None:
    # Given: malformed JSON before a valid-looking trailing fragment.
    journal = OfficeJobJournal(tmp_path)
    path = journal.path_for("broken")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not-json\n{\"job_id\":\"broken\"")

    # When: restoration parses the complete journal records.
    with pytest.raises(DocumentError) as caught:
        journal.restore("broken", runner=FakeRunner())

    # Then: corruption is a typed precondition failure, not silently skipped.
    assert caught.value.code is DocumentErrorCode.PRECONDITION_FAILED
    assert caught.value.stage == "office_job_journal"


def test_restore_rejects_schema_invalid_earlier_snapshot(tmp_path: Path) -> None:
    # Given: an invalid complete record before a valid latest snapshot.
    journal = OfficeJobJournal(tmp_path)
    _job(journal)
    path = journal.path_for("job-1")
    path.write_bytes(b'{"job_id":"job-1"}\n' + path.read_bytes())

    # When: restoration checks the complete append history.
    with pytest.raises(DocumentError) as caught:
        journal.restore("job-1", runner=FakeRunner())

    # Then: an earlier corrupt snapshot cannot be hidden by a later valid one.
    assert caught.value.code is DocumentErrorCode.PRECONDITION_FAILED
    assert caught.value.stage == "office_job_journal"


def test_terminal_and_incomplete_job_listings_use_latest_snapshot(tmp_path: Path) -> None:
    # Given: one completed export, one validated draft, and one active job.
    journal = OfficeJobJournal(tmp_path)
    terminal = OfficeJob(
        job_id="terminal",
        format_name="docx",
        source={"uri": "source.docx"},
        runner=FakeRunner(),
        journal=journal,
    )
    _advance_to_validated(terminal)
    terminal.publish(output_name="final.docx")
    terminal.export(_export_request(tmp_path / "final.docx"))
    validated = OfficeJob(
        job_id="validated",
        format_name="docx",
        source={"uri": "source.docx"},
        runner=FakeRunner(),
        journal=journal,
    )
    _advance_to_validated(validated)
    incomplete = OfficeJob(
        job_id="incomplete",
        format_name="docx",
        source={"uri": "source.docx"},
        runner=FakeRunner(),
        journal=journal,
    )
    incomplete.declare_outcome("Still running")

    # When: the workspace indexes jobs by latest complete state.
    terminal_ids = journal.list_terminal()
    incomplete_ids = journal.list_incomplete()

    # Then: each job appears in exactly its lifecycle partition.
    assert terminal_ids == ("terminal",)
    assert incomplete_ids == ("incomplete", "validated")
