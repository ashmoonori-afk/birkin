from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from birkin import approvals, config, store
from birkin.office.job import OfficeJob
from birkin.office.job_journal import OfficeJobJournal
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.job_types import OfficeJobState
from birkin.office.service import DocumentService
from tests.office.test_office_coordinator import _queue, _sha256


class SimulatedCrash(BaseException):
    """Terminate the approval path without its exception recovery boundary."""


def _restore(payload: dict[str, object]) -> OfficeJob:
    home = config.birkin_home() / "office"
    runner = DocumentServiceRunner(
        DocumentService(home), export_root=Path(cast(str, payload["allowlist_root"]))
    )
    return OfficeJobJournal(home / "jobs").restore(
        cast(str, payload["job_id"]), runner=runner
    )


def test_executing_approval_claim_is_resumable_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a process that durably claimed approval and died before coordinator entry.
    body, record, source, destination, source_sha256 = _queue(tmp_path, monkeypatch)
    approval_id = cast(str, body["id"])
    assert approvals.claim(approval_id)["ok"] is True
    _ = store.resolve_pending(approval_id, "executing")

    # When: a restarted process approves the same durable authority.
    result = approvals.approve(approval_id)

    # Then: it resumes once rather than stranding or duplicating the mutation.
    assert result["ok"] is True, result
    payload = cast("dict[str, object]", record["payload"])
    restored = _restore(payload)
    assert restored.state is OfficeJobState.exported
    assert restored.history.count(OfficeJobState.approved) == 1
    assert restored.history.count(OfficeJobState.executed) == 1
    assert restored.history.count(OfficeJobState.exported) == 1
    assert _sha256(source) == source_sha256
    assert destination.is_file()


@pytest.mark.parametrize(
    "checkpoint",
    [
        OfficeJobState.approved,
        OfficeJobState.executed,
        OfficeJobState.validated,
        OfficeJobState.exported,
    ],
)
def test_each_durable_job_checkpoint_resumes_without_repeating_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    checkpoint: OfficeJobState,
) -> None:
    # Given: a coordinator crash immediately after one durable phase checkpoint.
    body, record, source, destination, source_sha256 = _queue(tmp_path, monkeypatch)
    approval_id = cast(str, body["id"])
    real_append = OfficeJobJournal.append
    crashed = False

    def crash_after_checkpoint(self: OfficeJobJournal, job: OfficeJob) -> None:
        nonlocal crashed
        real_append(self, job)
        if job.state is checkpoint and not crashed:
            crashed = True
            raise SimulatedCrash

    monkeypatch.setattr(OfficeJobJournal, "append", crash_after_checkpoint)
    with pytest.raises(SimulatedCrash):
        _ = approvals.approve(approval_id)
    monkeypatch.setattr(OfficeJobJournal, "append", real_append)
    pending = store.get_pending(approval_id)
    assert pending is not None
    assert pending["status"] == "executing"

    # When: a new coordinator resumes from the latest complete snapshot.
    result = approvals.approve(approval_id)

    # Then: every completed phase remains singular and the export finishes.
    assert result["ok"] is True, result
    payload = cast("dict[str, object]", record["payload"])
    restored = _restore(payload)
    assert restored.state is OfficeJobState.exported
    assert restored.history.count(checkpoint) == 1
    assert _sha256(source) == source_sha256
    assert destination.is_file()


def test_publication_commit_before_job_snapshot_is_reconciled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: publication commits, then the process dies before OfficeJob stores it.
    body, record, source, destination, source_sha256 = _queue(tmp_path, monkeypatch)
    approval_id = cast(str, body["id"])
    real_publish = DocumentServiceRunner.publish
    crashed = False

    def crash_after_publish(
        self: DocumentServiceRunner,
        *,
        artifact: dict[str, object],
        output_name: str,
    ) -> dict[str, object]:
        nonlocal crashed
        publication = real_publish(self, artifact=artifact, output_name=output_name)
        if not crashed:
            crashed = True
            raise SimulatedCrash
        return publication

    monkeypatch.setattr(DocumentServiceRunner, "publish", crash_after_publish)
    with pytest.raises(SimulatedCrash):
        _ = approvals.approve(approval_id)
    monkeypatch.setattr(DocumentServiceRunner, "publish", real_publish)

    # When: restart resumes a validated job with its deterministic output present.
    result = approvals.approve(approval_id)

    # Then: publication is reconciled and export reaches the exact destination.
    assert result["ok"] is True, result
    payload = cast("dict[str, object]", record["payload"])
    restored = _restore(payload)
    assert restored.state is OfficeJobState.exported
    assert _sha256(source) == source_sha256
    assert destination.is_file()


def test_rollback_commit_before_job_snapshot_is_reconciled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: an exported job whose destination rollback commits before process exit.
    body, record, source, destination, source_sha256 = _queue(tmp_path, monkeypatch)
    approval_id = cast(str, body["id"])
    assert approvals.approve(approval_id)["ok"] is True
    payload = cast("dict[str, object]", record["payload"])
    job = _restore(payload)
    real_rollback = DocumentServiceRunner.rollback_export
    crashed = False

    def crash_after_rollback(
        self: DocumentServiceRunner, receipt: Mapping[str, object]
    ) -> Mapping[str, object]:
        nonlocal crashed
        result = real_rollback(self, receipt)
        if not crashed:
            crashed = True
            raise SimulatedCrash
        return result

    monkeypatch.setattr(DocumentServiceRunner, "rollback_export", crash_after_rollback)

    # When: the process exits before OfficeJob appends its validated state.
    with pytest.raises(SimulatedCrash):
        _ = job.rollback_export()
    monkeypatch.setattr(DocumentServiceRunner, "rollback_export", real_rollback)
    restored = _restore(payload)
    rollback = restored.rollback_export()

    # Then: rollback is observed once and its durable job transition completes.
    assert rollback["restored"] is False
    assert restored.state is OfficeJobState.validated
    assert not destination.exists()
    assert _sha256(source) == source_sha256
