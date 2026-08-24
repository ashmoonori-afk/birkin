from __future__ import annotations

import errno
from pathlib import Path

import pytest

from birkin.office import export_policy
from birkin.office.errors import DocumentError
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.service import DocumentService
from tests.office.test_export_policy import _request, _validated_draft


class SimulatedCrash(BaseException):
    """Hard exit after a filesystem side effect, before its next checkpoint."""


def test_directory_sync_failure_restores_overwritten_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: an approved overwrite and a one-shot destination-directory fsync fault.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service, "new validated bytes")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    original = b"caller original bytes"
    _ = destination.write_bytes(original)
    real_sync = export_policy.sync_directory
    failed = False

    def fail_first_destination_sync(path: Path, identity: tuple[int, int]) -> None:
        nonlocal failed
        if path == caller and not failed:
            failed = True
            raise OSError(errno.EIO, "injected directory fsync failure")
        real_sync(path, identity)

    monkeypatch.setattr(export_policy, "sync_directory", fail_first_destination_sync)

    # When: replacement succeeds but its directory durability proof fails.
    with pytest.raises(DocumentError) as caught:
        _ = DocumentServiceRunner(service, export_root=caller).export(
            artifact=artifact,
            request=_request(destination, overwrite_approved=True),
        )

    # Then: the original is restored atomically and no rollback material is needed.
    assert caught.value.retryable is True
    assert destination.read_bytes() == original
    backup_root = service.home / "artifacts" / "export-backups"
    assert not backup_root.exists() or not tuple(backup_root.iterdir())


def test_failed_compensation_keeps_rollback_material_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: destination fsync fails for both commit and immediate compensation.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service, "new validated bytes")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    original = b"caller original before recovery"
    _ = destination.write_bytes(original)
    real_sync = export_policy.sync_directory

    def fail_destination_sync(path: Path, identity: tuple[int, int]) -> None:
        if path == caller:
            raise OSError(errno.EIO, "injected persistent directory fsync failure")
        real_sync(path, identity)

    monkeypatch.setattr(export_policy, "sync_directory", fail_destination_sync)
    runner = DocumentServiceRunner(service, export_root=caller)
    request = _request(destination, overwrite_approved=True)

    # When: immediate restoration cannot establish directory durability either.
    with pytest.raises(DocumentError) as caught:
        _ = runner.export(artifact=artifact, request=request)

    # Then: original bytes and a durable recovery record remain available.
    assert caught.value.retryable is True
    assert destination.read_bytes() == original
    backups = tuple((service.home / "artifacts" / "export-backups").glob("*.bak"))
    transactions = tuple((service.home / "artifacts" / "export-journal").glob("*.json"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    assert len(transactions) == 1

    # When: a restarted runner resumes after the filesystem fault clears.
    monkeypatch.setattr(export_policy, "sync_directory", real_sync)
    receipt = DocumentServiceRunner(service, export_root=caller).export(
        artifact=artifact, request=request
    )

    # Then: the approved bytes commit once and retain exact rollback authority.
    assert destination.read_text(encoding="utf-8") == "new validated bytes"
    rollback = DocumentServiceRunner(service, export_root=caller).rollback_export(receipt)
    assert rollback["restored"] is True
    assert destination.read_bytes() == original


def test_crash_after_backup_cleanup_keeps_export_resumable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: commit fsync fails, compensation restores original bytes, then cleanup crashes.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service, "new validated bytes")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    original = b"caller original before cleanup crash"
    _ = destination.write_bytes(original)
    real_sync = export_policy.sync_directory
    sync_failed = False

    def fail_commit_sync(path: Path, identity: tuple[int, int]) -> None:
        nonlocal sync_failed
        if path == caller and not sync_failed:
            sync_failed = True
            raise OSError(errno.EIO, "injected commit directory fsync failure")
        real_sync(path, identity)

    real_unlink = Path.unlink
    crashed = False

    def crash_after_backup_unlink(path: Path, missing_ok: bool = False) -> None:
        nonlocal crashed
        real_unlink(path, missing_ok=missing_ok)
        if path.suffix == ".bak" and not crashed:
            crashed = True
            raise SimulatedCrash

    monkeypatch.setattr(export_policy, "sync_directory", fail_commit_sync)
    monkeypatch.setattr(Path, "unlink", crash_after_backup_unlink)
    request = _request(destination, overwrite_approved=True)

    # When: the process exits after deleting backup bytes but before journal cleanup.
    with pytest.raises(SimulatedCrash):
        _ = DocumentServiceRunner(service, export_root=caller).export(
            artifact=artifact, request=request
        )
    monkeypatch.setattr(Path, "unlink", real_unlink)
    monkeypatch.setattr(export_policy, "sync_directory", real_sync)

    # Then: a fresh runner recognizes completed compensation and safely commits once.
    receipt = DocumentServiceRunner(service, export_root=caller).export(
        artifact=artifact, request=request
    )
    assert destination.read_text(encoding="utf-8") == "new validated bytes"
    rollback = DocumentServiceRunner(service, export_root=caller).rollback_export(receipt)
    assert rollback["restored"] is True
    assert destination.read_bytes() == original
