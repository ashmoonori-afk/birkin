from __future__ import annotations

import errno
import os
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


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink semantics")
def test_job_journal_refuses_symlinked_snapshot(
    tmp_path: Path,
) -> None:
    journal = OfficeJobJournal(tmp_path / "jobs")
    victim = tmp_path / "victim.jsonl"
    _ = victim.write_text('{"secret":"preserve"}\n', encoding="utf-8")
    journal.path_for("linked").symlink_to(victim)

    with pytest.raises(DocumentError, match="snapshot is unavailable"):
        _ = journal.latest("linked")

    assert victim.read_text(encoding="utf-8") == '{"secret":"preserve"}\n'


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink semantics")
def test_job_journal_refuses_append_through_symlink(
    tmp_path: Path,
) -> None:
    journal = OfficeJobJournal(tmp_path / "jobs")
    victim = tmp_path / "victim.jsonl"
    _ = victim.write_text("preserve\n", encoding="utf-8")
    journal.path_for("linked").symlink_to(victim)

    with pytest.raises(DocumentError, match="durability failed"):
        _ = OfficeJob(
            job_id="linked",
            format_name="docx",
            source={"uri": "source.docx"},
            runner=FakeRunner(),
            journal=journal,
        )

    assert victim.read_text(encoding="utf-8") == "preserve\n"
