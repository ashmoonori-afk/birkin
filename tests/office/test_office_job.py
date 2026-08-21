from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.job import OfficeJob, OfficeJobState


class FakeRunner:
    def __init__(self, *, validation_status: str = "pass") -> None:
        self.preview_calls = 0
        self.execute_calls = 0
        self.validate_calls = 0
        self.publish_calls = 0
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
            "artifact": {"uri": output_name, "content_hash": "published-sha"},
            "sha256": "published-sha",
        }


def _job(*, validation_status: str = "pass") -> tuple[OfficeJob, FakeRunner]:
    runner = FakeRunner(validation_status=validation_status)
    job = OfficeJob(
        job_id="job-1",
        format_name="docx",
        source={"uri": "source.docx", "content_hash": "source-sha"},
        runner=runner,
    )
    return job, runner


def _advance_to_approval(job: OfficeJob) -> None:
    job.declare_outcome("Replace the heading")
    job.propose_operations([{"type": "replace_text", "value": "New"}])
    job.build_preview()
    job.request_approval()


def _assert_error_code(caught: pytest.ExceptionInfo[DocumentError], code: DocumentErrorCode) -> None:
    assert caught.value.code is code
    assert caught.value.stage == "office_job"


def test_happy_path_has_exact_state_sequence() -> None:
    job, runner = _job()

    _advance_to_approval(job)
    job.approve(actor="reviewer")
    job.execute()
    job.validate()
    job.publish(output_name="final.docx")

    assert job.history == (
        OfficeJobState.input_captured,
        OfficeJobState.outcome_declared,
        OfficeJobState.operations_proposed,
        OfficeJobState.preview_ready,
        OfficeJobState.approval_requested,
        OfficeJobState.approved,
        OfficeJobState.executed,
        OfficeJobState.validated,
        OfficeJobState.published,
    )
    assert (runner.preview_calls, runner.execute_calls, runner.validate_calls, runner.publish_calls) == (
        1,
        1,
        1,
        1,
    )


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
    job.approve(actor="reviewer")

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
    job.reject(actor="reviewer", reason="Needs revision")

    with pytest.raises(DocumentError) as caught:
        job.execute()

    _assert_error_code(caught, DocumentErrorCode.PRECONDITION_FAILED)
    assert job.state is OfficeJobState.rejected
    assert runner.execute_calls == 0


def test_changed_operations_after_approval_are_rejected_without_runner_call() -> None:
    job, runner = _job()
    _advance_to_approval(job)
    job.approve(actor="reviewer")
    job._operations.append({"type": "injected"})

    with pytest.raises(DocumentError) as caught:
        job.execute()

    _assert_error_code(caught, DocumentErrorCode.PRECONDITION_FAILED)
    assert runner.execute_calls == 0
    assert job.state is OfficeJobState.approved


def test_failed_validation_blocks_publication_without_runner_call() -> None:
    job, runner = _job(validation_status="fail")
    _advance_to_approval(job)
    job.approve(actor="reviewer")
    job.execute()

    report = job.validate()

    assert report == {"status": "fail", "valid": False}
    assert job.state is OfficeJobState.failed
    with pytest.raises(DocumentError) as caught:
        job.publish(output_name="final.docx")
    _assert_error_code(caught, DocumentErrorCode.PRECONDITION_FAILED)
    assert runner.publish_calls == 0


def test_receipt_has_fixed_keys_and_pending_values_are_none() -> None:
    job, _runner = _job()
    initial = job.receipt()
    expected_keys = {
        "job_id",
        "format",
        "state",
        "history",
        "outcome",
        "operations",
        "preview",
        "approval",
        "execution",
        "validation",
        "publication",
    }
    assert set(initial) == expected_keys
    assert initial == {
        "job_id": "job-1",
        "format": "docx",
        "state": "input_captured",
        "history": ["input_captured"],
        "outcome": None,
        "operations": None,
        "preview": None,
        "approval": None,
        "execution": None,
        "validation": None,
        "publication": None,
    }

    _advance_to_approval(job)
    job.approve(actor="reviewer")
    job.execute()
    job.validate()
    job.publish(output_name="final.docx")
    completed = job.receipt()

    assert set(completed) == expected_keys
    assert completed["state"] == "published"
    assert completed["outcome"] == "Replace the heading"
    assert completed["operations"] == [{"type": "replace_text", "value": "New"}]
    assert completed["preview"] is not None
    assert completed["execution"] is not None
    assert completed["validation"] is not None
    assert completed["publication"] is not None
    approval = completed["approval"]
    assert isinstance(approval, dict)
    assert set(approval) == {"decision", "actor", "at", "proposal_digest"}
    assert approval["decision"] == "approved"
    assert approval["actor"] == "reviewer"
    assert isinstance(approval["at"], str)
    assert isinstance(approval["proposal_digest"], str)
