from __future__ import annotations

from pathlib import Path

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.job import OfficeJob, OfficeJobState
from birkin.office.job_journal import OfficeJobJournal
from tests.office.test_office_job_journal import (
    FakeRunner,
    _advance_to_validated,
    _export_request,
    _job,
)


def test_validated_and_exported_snapshots_restore_exactly(tmp_path: Path) -> None:
    # Given: one internal validated draft and its caller export request.
    journal = OfficeJobJournal(tmp_path / "journal")
    job, _runner = _job(journal)
    _advance_to_validated(job)
    job.publish(output_name="final.docx")
    validated = job.to_dict()

    # When: each lifecycle point crosses the durable journal boundary.
    restored_validated = journal.restore("job-1", runner=FakeRunner())
    job.export(_export_request(tmp_path / "final.docx"))
    exported = job.to_dict()
    restored_exported = journal.restore("job-1", runner=FakeRunner())

    # Then: state, receipts, and history are exact at each point.
    assert restored_validated.to_dict() == validated
    assert restored_validated.state is OfficeJobState.validated
    assert restored_exported.to_dict() == exported
    assert restored_exported.state is OfficeJobState.exported
    assert exported["export"] is not None
    assert exported["rollback"] is None

    restored_exported.rollback_export()
    rolled_back = restored_exported.to_dict()
    assert journal.restore("job-1", runner=FakeRunner()).to_dict() == rolled_back
    assert rolled_back["state"] == "validated"
    assert rolled_back["rollback"] is not None


def test_legacy_published_snapshot_is_rejected_as_typed_precondition() -> None:
    # Given: an otherwise valid snapshot carrying the removed terminal state.
    job, _runner = _job()
    snapshot = job.to_dict()
    snapshot["state"] = "published"
    snapshot["history"] = ["published"]

    # When: the legacy snapshot crosses the restore boundary.
    with pytest.raises(DocumentError) as caught:
        OfficeJob.from_dict(snapshot, runner=FakeRunner())

    # Then: no compatibility state is silently invented.
    assert caught.value.code is DocumentErrorCode.PRECONDITION_FAILED
    assert caught.value.stage == "office_job_journal"
