from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from birkin.office.artifact_snapshot import SnapshotPath
from birkin.office.export_commit import ExportCommit
from birkin.office.export_journal import ExportJournal, ExportPhase, ExportTransaction
from birkin.office.export_policy import JSONValue, ExportRequest
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.service import DocumentService
from birkin.office.service_types import ArtifactRef
from tests.office.test_export_policy import _request, _validated_draft


class SimulatedCrash(BaseException):
    """Terminate between a filesystem side effect and its next checkpoint."""


@dataclass(frozen=True, slots=True)
class ExportFixture:
    service: DocumentService
    artifact: ArtifactRef
    caller: Path
    destination: Path
    request: ExportRequest
    original: bytes | None


def _fixture(tmp_path: Path, *, overwrite: bool = False) -> ExportFixture:
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service, "validated phase bytes")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    original = b"original phase bytes" if overwrite else None
    if original is not None:
        _ = destination.write_bytes(original)
    return ExportFixture(
        service=service,
        artifact=artifact,
        caller=caller,
        destination=destination,
        request=_request(destination, overwrite_approved=overwrite),
        original=original,
    )


def _resume(fixture: ExportFixture) -> dict[str, JSONValue]:
    return DocumentServiceRunner(
        fixture.service, export_root=fixture.caller
    ).export(artifact=fixture.artifact, request=fixture.request)


@pytest.mark.parametrize(
    "phase",
    [ExportPhase.intent, ExportPhase.prepared, ExportPhase.committed],
)
def test_each_export_journal_checkpoint_resumes_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: ExportPhase,
) -> None:
    # Given: a hard exit immediately after one complete transaction record.
    fixture = _fixture(tmp_path)
    real_write = ExportJournal.write
    crashed = False

    def crash_after_write(
        self: ExportJournal, transaction: ExportTransaction
    ) -> None:
        nonlocal crashed
        real_write(self, transaction)
        if transaction.phase is phase and not crashed:
            crashed = True
            raise SimulatedCrash

    monkeypatch.setattr(ExportJournal, "write", crash_after_write)
    with pytest.raises(SimulatedCrash):
        _ = _resume(fixture)
    monkeypatch.setattr(ExportJournal, "write", real_write)

    # When: a fresh runner resumes the exact authority.
    receipt = _resume(fixture)

    # Then: the caller sees one output and its rollback removes the new path.
    assert fixture.destination.read_text(encoding="utf-8") == "validated phase bytes"
    rollback = DocumentServiceRunner(
        fixture.service, export_root=fixture.caller
    ).rollback_export(receipt)
    assert rollback["restored"] is False
    assert not fixture.destination.exists()


def test_backup_commit_before_prepared_checkpoint_is_reconciled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: overwrite backup rename completes before the process exits.
    fixture = _fixture(tmp_path, overwrite=True)
    real_replace = os.replace
    crashed = False

    def crash_after_backup(source: Path, target: Path) -> None:
        nonlocal crashed
        real_replace(source, target)
        if Path(target).suffix == ".bak" and not crashed:
            crashed = True
            raise SimulatedCrash

    monkeypatch.setattr(os, "replace", crash_after_backup)
    with pytest.raises(SimulatedCrash):
        _ = _resume(fixture)
    monkeypatch.setattr(os, "replace", real_replace)

    # When: restart finds the intent and exact backup bytes.
    receipt = _resume(fixture)

    # Then: export completes and rollback retains the original byte identity.
    rollback = DocumentServiceRunner(
        fixture.service, export_root=fixture.caller
    ).rollback_export(receipt)
    assert rollback["restored"] is True
    assert fixture.destination.read_bytes() == fixture.original


@pytest.mark.parametrize("boundary", ["reservation", "staging"])
def test_precommit_files_are_reused_after_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    # Given: one deterministic precommit file is complete when the process exits.
    fixture = _fixture(tmp_path)
    crashed = False
    if boundary == "reservation":
        original = ExportCommit._reserve_new

        def crash_after_reservation(transaction: ExportTransaction) -> None:
            nonlocal crashed
            original(transaction)
            if not crashed:
                crashed = True
                raise SimulatedCrash

        monkeypatch.setattr(
            ExportCommit, "_reserve_new", staticmethod(crash_after_reservation)
        )
    else:
        original_stage = ExportCommit._stage

        def crash_after_staging(
            transaction: ExportTransaction, source: SnapshotPath
        ) -> None:
            nonlocal crashed
            original_stage(transaction, source)
            if not crashed:
                crashed = True
                raise SimulatedCrash

        monkeypatch.setattr(ExportCommit, "_stage", staticmethod(crash_after_staging))

    # When: the first process exits and a fresh runner resumes.
    with pytest.raises(SimulatedCrash):
        _ = _resume(fixture)
    monkeypatch.undo()
    receipt = _resume(fixture)

    # Then: no helper path is stranded and the exact export is rollback-capable.
    assert fixture.destination.read_text(encoding="utf-8") == "validated phase bytes"
    assert not tuple(fixture.caller.glob(".birkin-export-*"))
    rollback = DocumentServiceRunner(
        fixture.service, export_root=fixture.caller
    ).rollback_export(receipt)
    assert rollback["restored"] is False
