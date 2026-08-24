from __future__ import annotations

import errno
from pathlib import Path

import pytest

from birkin.office import job_journal
from birkin.office.errors import DocumentError
from birkin.office.job import OfficeJob
from birkin.office.job_journal import OfficeJobJournal
from birkin.office.job_types import OfficeJobState
from tests.office.test_office_job_journal import FakeRunner


def test_directory_sync_failure_keeps_complete_job_checkpoint_resumable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a journal whose file append completes before directory sync fails.
    journal = OfficeJobJournal(tmp_path / "jobs")
    job = OfficeJob(
        job_id="sync-fault",
        format_name="docx",
        source={"uri": "source.docx"},
        runner=FakeRunner(),
        journal=journal,
    )

    def fail_directory_sync(_path: Path, _identity: tuple[int, int]) -> None:
        raise OSError(errno.EIO, "injected job directory fsync failure")

    monkeypatch.setattr(job_journal, "sync_directory", fail_directory_sync, raising=False)

    # When: the next state checkpoint reaches its directory durability boundary.
    with pytest.raises(DocumentError) as caught:
        job.declare_outcome("Durable after restart")

    # Then: retry is explicit and the newline-complete snapshot is recoverable.
    assert caught.value.retryable is True
    restored = journal.restore("sync-fault", runner=FakeRunner())
    assert restored.state is OfficeJobState.outcome_declared
    assert restored.history[-1] is OfficeJobState.outcome_declared
