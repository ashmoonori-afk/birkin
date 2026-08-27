from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from birkin.office import export_commit
from birkin.office.artifact_snapshot import SnapshotPath
from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.export_commit import ExportCommit
from birkin.office.export_journal import ExportJournal, ExportPhase, ExportTransaction
from birkin.office.export_policy import JSONValue, ExportRequest
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.proposal_integrity import authority_digest
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


@pytest.mark.parametrize(
    "phase",
    [ExportPhase.intent, ExportPhase.prepared, ExportPhase.committed],
)
def test_v1_export_journal_checkpoint_upgrades_before_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: ExportPhase,
) -> None:
    # Given: a V1 checkpoint persisted before authority used the input digest.
    fixture = _fixture(tmp_path)
    original_source_sha256 = "a" * 64
    request = replace(
        fixture.request,
        authority_source_sha256=original_source_sha256,
    )
    request = replace(
        request,
        authority_digest=authority_digest(
            fixture.destination,
            original_source_sha256,
            request,
        ),
    )
    fixture = replace(fixture, request=request)
    real_write = ExportJournal.write

    def crash_after_intent(
        self: ExportJournal,
        transaction: ExportTransaction,
    ) -> None:
        real_write(self, transaction)
        if transaction.phase is phase:
            raise SimulatedCrash

    monkeypatch.setattr(ExportJournal, "write", crash_after_intent)
    with pytest.raises(SimulatedCrash):
        _ = _resume(fixture)
    monkeypatch.setattr(ExportJournal, "write", real_write)
    journal_path = next(
        (fixture.service.home / "artifacts" / "export-journal").glob("*.json")
    )
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    record["version"] = 1
    del record["authority_digest"]
    del record["authority_source_sha256"]
    journal_path.write_text(json.dumps(record), encoding="utf-8")

    # When: the authority-bearing request resumes the old transaction.
    receipt = _resume(fixture)

    # Then: recovery completes under the approved authority and upgrades the record.
    upgraded = json.loads(journal_path.read_text(encoding="utf-8"))
    assert receipt["authority_digest"] == request.authority_digest
    assert receipt["authority_source_sha256"] == original_source_sha256
    assert upgraded["version"] == 2
    assert upgraded["authority_digest"] == request.authority_digest
    assert upgraded["authority_source_sha256"] == original_source_sha256
    assert fixture.destination.read_text(encoding="utf-8") == "validated phase bytes"


def test_rolled_back_journal_is_verified_before_retiring_paths(
    tmp_path: Path,
) -> None:
    # Given: a rolled-back journal whose staging path was changed after approval.
    fixture = _fixture(tmp_path)
    receipt = _resume(fixture)
    _ = DocumentServiceRunner(
        fixture.service,
        export_root=fixture.caller,
    ).rollback_export(receipt)
    victim = fixture.caller / "must-not-delete.txt"
    victim.write_text("preserve me", encoding="utf-8")
    journal_path = next(
        (fixture.service.home / "artifacts" / "export-journal").glob("*.json")
    )
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    record["staging"] = str(victim)
    journal_path.write_text(json.dumps(record), encoding="utf-8")

    # When: replay attempts to retire the tampered transaction.
    with pytest.raises(DocumentError) as caught:
        _ = _resume(fixture)

    # Then: authority fails before the journal-selected path can be unlinked.
    assert caught.value.code is DocumentErrorCode.POLICY_DENIED
    assert victim.read_text(encoding="utf-8") == "preserve me"
    assert not fixture.destination.exists()


def test_rolled_back_journal_cannot_retire_another_backup(
    tmp_path: Path,
) -> None:
    # Given: a rolled-back journal whose backup points at a sibling backup file.
    fixture = _fixture(tmp_path, overwrite=True)
    receipt = _resume(fixture)
    _ = DocumentServiceRunner(
        fixture.service,
        export_root=fixture.caller,
    ).rollback_export(receipt)
    backup_root = fixture.service.home / "artifacts" / "export-backups"
    victim = backup_root / "must-not-delete.bak"
    victim.write_text("preserve me", encoding="utf-8")
    journal_path = next(
        (fixture.service.home / "artifacts" / "export-journal").glob("*.json")
    )
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    record["backup"] = str(victim)
    journal_path.write_text(json.dumps(record), encoding="utf-8")

    # When: replay attempts to retire the tampered transaction.
    with pytest.raises(DocumentError) as caught:
        _ = _resume(fixture)

    # Then: exact backup identity fails before cleanup can unlink the sibling.
    assert caught.value.code is DocumentErrorCode.POLICY_DENIED
    assert victim.read_text(encoding="utf-8") == "preserve me"
    assert fixture.destination.read_bytes() == fixture.original


def test_export_rejects_matching_staging_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the deterministic staging path is preempted by matching symlink bytes.
    fixture = _fixture(tmp_path, overwrite=True)
    real_stage = ExportCommit._stage

    def inject_symlink(
        transaction: ExportTransaction,
        source: SnapshotPath,
    ) -> None:
        transaction.staging.symlink_to(Path(source))
        real_stage(transaction, source)

    monkeypatch.setattr(ExportCommit, "_stage", staticmethod(inject_symlink))

    # When: export attempts to reuse the preempted staging path.
    with pytest.raises(DocumentError):
        _ = _resume(fixture)

    # Then: the caller's original remains a regular file.
    assert not fixture.destination.is_symlink()
    assert fixture.destination.read_bytes() == fixture.original


def test_export_rejects_matching_backup_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: rollback material is preempted by a symlink to matching original bytes.
    fixture = _fixture(tmp_path, overwrite=True)
    real_prepare = ExportCommit.prepare

    def inject_symlink(
        self: ExportCommit,
        transaction: ExportTransaction,
    ) -> ExportTransaction:
        assert transaction.backup is not None
        transaction.backup.parent.mkdir(parents=True, exist_ok=True)
        transaction.backup.symlink_to(transaction.destination)
        return real_prepare(self, transaction)

    monkeypatch.setattr(ExportCommit, "prepare", inject_symlink)

    # When: export attempts to accept the preempted backup.
    with pytest.raises(DocumentError):
        _ = _resume(fixture)

    # Then: the caller's original remains a regular file.
    assert not fixture.destination.is_symlink()
    assert fixture.destination.read_bytes() == fixture.original


def test_export_rejects_staging_swapped_during_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: staging is replaced by matching symlink bytes while being hashed.
    fixture = _fixture(tmp_path, overwrite=True)
    real_hash = export_commit.hash_file
    artifact = Path(str(fixture.artifact["uri"]))
    swapped = False

    def swap_during_hash(path: Path) -> str:
        nonlocal swapped
        if path.parent == fixture.caller and path.name.startswith(".birkin-export-"):
            path.unlink()
            path.symlink_to(artifact)
            swapped = True
        return real_hash(path)

    monkeypatch.setattr(export_commit, "hash_file", swap_during_hash)

    # When: export reaches its post-copy staging hash.
    with pytest.raises(DocumentError):
        _ = _resume(fixture)

    # Then: the symlink is never published over the caller's original.
    assert swapped is True
    assert not fixture.destination.is_symlink()
    assert fixture.destination.read_bytes() == fixture.original


def test_export_rejects_staging_swapped_after_final_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: staging becomes a matching symlink after the final hash returns.
    fixture = _fixture(tmp_path, overwrite=True)
    real_hash = export_commit.hash_file
    artifact = Path(str(fixture.artifact["uri"]))
    staging_hashes = 0

    def swap_after_final_hash(path: Path) -> str:
        nonlocal staging_hashes
        digest = real_hash(path)
        if path.parent == fixture.caller and path.name.startswith(".birkin-export-"):
            staging_hashes += 1
            if staging_hashes == 2:
                path.unlink()
                path.symlink_to(artifact)
        return digest

    monkeypatch.setattr(export_commit, "hash_file", swap_after_final_hash)

    # When: export reaches atomic replacement after final verification.
    with pytest.raises(DocumentError):
        _ = _resume(fixture)

    # Then: the changed inode is not published.
    assert staging_hashes == 2
    assert not fixture.destination.is_symlink()
    assert fixture.destination.read_bytes() == fixture.original


def test_export_rejects_backup_swapped_after_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: copied rollback material becomes a matching symlink before replacement.
    fixture = _fixture(tmp_path, overwrite=True)
    real_copy = export_commit.copy_exact
    swapped = False

    def swap_after_copy(source: Path, target: Path) -> None:
        nonlocal swapped
        real_copy(source, target)
        if target.name.endswith(".prepare"):
            target.unlink()
            target.symlink_to(fixture.destination)
            swapped = True

    monkeypatch.setattr(export_commit, "copy_exact", swap_after_copy)

    # When: export prepares rollback material.
    with pytest.raises(DocumentError):
        _ = _resume(fixture)

    # Then: symlinked rollback material is not accepted.
    assert swapped is True
    assert not fixture.destination.is_symlink()
    assert fixture.destination.read_bytes() == fixture.original


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
