from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.export_policy import ExportRequest
from birkin.office.job import OfficeJob, OfficeJobState


class FakeRunner:
    def __init__(self, *, validation_status: str = "pass") -> None:
        self.preview_calls = 0
        self.execute_calls = 0
        self.validate_calls = 0
        self.publish_calls = 0
        self.export_calls = 0
        self.rollback_calls = 0
        self.validation_status = validation_status

    def preview(
        self,
        *,
        source: Mapping[str, object],
        format_name: str,
        operations: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        self.preview_calls += 1
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
        self.validate_calls += 1
        return {
            "status": self.validation_status,
            "valid": self.validation_status != "fail",
        }

    def publish(
        self, *, artifact: Mapping[str, object], output_name: str
    ) -> dict[str, object]:
        self.publish_calls += 1
        return {
            "artifact": {"uri": f"drafts/{output_name}", "content_hash": "published-sha"},
            "sha256": "published-sha",
            "path": f"drafts/{output_name}",
        }

    def export(
        self, *, artifact: Mapping[str, object], request: ExportRequest
    ) -> dict[str, object]:
        self.export_calls += 1
        return {
            "path": str(request.destination),
            "source_sha256": artifact["content_hash"],
            "output_sha256": artifact["content_hash"],
            "rollback_token": "rollback-1",
        }

    def rollback_export(
        self, receipt: Mapping[str, object]
    ) -> dict[str, object]:
        self.rollback_calls += 1
        return {"path": receipt["path"], "restored": False}


def _job(*, validation_status: str = "pass") -> tuple[OfficeJob, FakeRunner]:
    runner = FakeRunner(validation_status=validation_status)
    job = OfficeJob(
        job_id="job-1",
        format_name="docx",
        source={"uri": "source.docx", "content_hash": "source-sha"},
        runner=runner,
    )
    return job, runner


def _request() -> ExportRequest:
    return ExportRequest(
        destination=Path("caller/final.docx"),
        actor="reviewer",
        proposal_digest="proposal-sha",
        operations=({"type": "replace_text", "value": "New"},),
    )


def _advance_to_approval(job: OfficeJob) -> None:
    job.declare_outcome("Replace the heading")
    job.propose_operations([{"type": "replace_text", "value": "New"}])
    job.build_preview()
    job.request_approval(proposer="test:proposer", authority_digest="a" * 64)


def _assert_error_code(caught: pytest.ExceptionInfo[DocumentError], code: DocumentErrorCode) -> None:
    assert caught.value.code is code
    assert caught.value.stage == "office_job"


def test_approval_request_binds_preview_source_and_proposal_digest() -> None:
    job, _runner = _job()

    job.declare_outcome("Replace the heading")
    job.propose_operations([{"type": "replace_text", "value": "New"}])
    job.build_preview()
    request = job.request_approval(proposer="test:proposer", authority_digest="a" * 64)

    assert request["source_sha256"] == "source-sha"
    assert isinstance(request["proposal_digest"], str)

    job.approve(approver="reviewer", approved_via="test:office-job")
    approval = job.receipt()["approval"]
    assert isinstance(approval, dict)
    assert request["proposal_digest"] == approval["proposal_digest"]


def test_happy_path_has_exact_state_sequence() -> None:
    job, runner = _job()

    _advance_to_approval(job)
    job.approve(approver="reviewer", approved_via="test:office-job")
    job.execute()
    job.validate()
    publication = job.publish(output_name="final.docx")
    assert job.state is OfficeJobState.validated
    export = job.export(_request())

    assert publication["path"] == "drafts/final.docx"
    assert Path(export["path"]) == Path("caller/final.docx")
    assert job.history == (
        OfficeJobState.input_captured,
        OfficeJobState.outcome_declared,
        OfficeJobState.operations_proposed,
        OfficeJobState.preview_ready,
        OfficeJobState.approval_requested,
        OfficeJobState.approved,
        OfficeJobState.executed,
        OfficeJobState.validated,
        OfficeJobState.exported,
    )
    assert (
        runner.preview_calls,
        runner.execute_calls,
        runner.validate_calls,
        runner.publish_calls,
        runner.export_calls,
    ) == (1, 1, 1, 1, 1)


def test_transition_sink_observes_every_office_job_stage() -> None:
    transitions: list[tuple[str, OfficeJobState]] = []
    runner = FakeRunner()
    job = OfficeJob(
        job_id="job-progress",
        format_name="docx",
        source={"uri": "source.docx", "content_hash": "source-sha"},
        runner=runner,
        on_transition=lambda job_id, state: transitions.append((job_id, state)),
    )

    _advance_to_approval(job)
    job.approve(approver="reviewer", approved_via="test:office-progress")
    job.execute()
    job.validate()
    _ = job.publish(output_name="final.docx")
    _ = job.export(_request())

    assert transitions == [
        ("job-progress", state)
        for state in (
            OfficeJobState.input_captured,
            OfficeJobState.outcome_declared,
            OfficeJobState.operations_proposed,
            OfficeJobState.preview_ready,
            OfficeJobState.approval_requested,
            OfficeJobState.approved,
            OfficeJobState.executed,
            OfficeJobState.validated,
            OfficeJobState.exported,
        )
    ]


def test_restored_job_transition_sink_observes_execution_stages() -> None:
    job, runner = _job()
    _advance_to_approval(job)
    transitions: list[tuple[str, OfficeJobState]] = []
    restored = OfficeJob.from_dict(
        job.to_dict(),
        runner=runner,
        on_transition=lambda job_id, state: transitions.append((job_id, state)),
    )

    restored.approve(approver="reviewer", approved_via="test:office-progress")
    restored.execute()
    restored.validate()
    _ = restored.publish(output_name="final.docx")
    _ = restored.export(_request())

    assert transitions == [
        ("job-1", OfficeJobState.approved),
        ("job-1", OfficeJobState.executed),
        ("job-1", OfficeJobState.validated),
        ("job-1", OfficeJobState.exported),
    ]


def test_export_requires_validated_internal_publication() -> None:
    job, runner = _job()
    _advance_to_approval(job)
    job.approve(approver="reviewer", approved_via="test:office-job")
    job.execute()
    job.validate()

    with pytest.raises(DocumentError) as caught:
        job.export(_request())

    _assert_error_code(caught, DocumentErrorCode.PRECONDITION_FAILED)
    assert job.state is OfficeJobState.validated
    assert runner.export_calls == 0


def test_rollback_returns_exported_job_to_validated_with_receipts() -> None:
    job, runner = _job()
    _advance_to_approval(job)
    job.approve(approver="reviewer", approved_via="test:office-job")
    job.execute()
    job.validate()
    job.publish(output_name="final.docx")
    job.export(_request())

    rollback = job.rollback_export()

    assert rollback == {"path": str(Path("caller/final.docx")), "restored": False}
    assert job.state is OfficeJobState.validated
    assert job.history[-3:] == (
        OfficeJobState.validated,
        OfficeJobState.exported,
        OfficeJobState.validated,
    )
    assert runner.rollback_calls == 1
    receipt = job.receipt()
    assert receipt["export"]["rollback_token"] == "rollback-1"
    assert receipt["rollback"] == rollback


def test_skipping_states_and_empty_operations_are_rejected() -> None:
    job, runner = _job()

    with pytest.raises(DocumentError) as preview_error:
        job.build_preview()
    _assert_error_code(preview_error, DocumentErrorCode.PRECONDITION_FAILED)
    with pytest.raises(DocumentError) as execute_error:
        job.execute()
    _assert_error_code(execute_error, DocumentErrorCode.PRECONDITION_FAILED)
    job.declare_outcome("Change it")
    with pytest.raises(DocumentError) as operations_error:
        job.propose_operations([])
    _assert_error_code(operations_error, DocumentErrorCode.INVALID_INPUT)
    assert runner.preview_calls == runner.execute_calls == 0


def test_cannot_return_to_operations_after_approval() -> None:
    job, _runner = _job()
    _advance_to_approval(job)
    job.approve(approver="reviewer", approved_via="test:office-job")

    with pytest.raises(DocumentError) as caught:
        job.propose_operations([{"type": "other"}])

    _assert_error_code(caught, DocumentErrorCode.PRECONDITION_FAILED)
    assert job.state is OfficeJobState.approved


def test_execution_without_approval_is_policy_denied_without_runner_call() -> None:
    job, runner = _job()
    _advance_to_approval(job)

    with pytest.raises(DocumentError) as caught:
        job.execute()

    _assert_error_code(caught, DocumentErrorCode.POLICY_DENIED)
    assert runner.execute_calls == 0
    assert job.state is OfficeJobState.approval_requested


def test_rejection_is_terminal() -> None:
    job, runner = _job()
    _advance_to_approval(job)
    job.reject(rejected_by="reviewer", rejected_via="test:office-job", reason="Needs revision")

    with pytest.raises(DocumentError) as caught:
        job.execute()

    _assert_error_code(caught, DocumentErrorCode.PRECONDITION_FAILED)
    assert job.state is OfficeJobState.rejected
    assert runner.execute_calls == 0


def test_changed_operations_after_approval_are_rejected_without_runner_call() -> None:
    job, runner = _job()
    _advance_to_approval(job)
    job.approve(approver="reviewer", approved_via="test:office-job")
    job._operations.append({"type": "injected"})

    with pytest.raises(DocumentError) as caught:
        job.execute()

    _assert_error_code(caught, DocumentErrorCode.PRECONDITION_FAILED)
    assert runner.execute_calls == 0
    assert job.state is OfficeJobState.approved


def test_failed_validation_blocks_publication_without_runner_call() -> None:
    job, runner = _job(validation_status="fail")
    _advance_to_approval(job)
    job.approve(approver="reviewer", approved_via="test:office-job")
    job.execute()

    report = job.validate()

    assert report == {"status": "fail", "valid": False}
    assert job.state is OfficeJobState.failed
    with pytest.raises(DocumentError) as caught:
        job.publish(output_name="final.docx")
    _assert_error_code(caught, DocumentErrorCode.PRECONDITION_FAILED)
    assert runner.publish_calls == 0
