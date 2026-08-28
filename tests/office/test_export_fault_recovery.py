from __future__ import annotations

import errno
import hashlib
import json
import uuid
from pathlib import Path

import pytest

from birkin.office import export_policy
from birkin.office import export_rollback_existing
from birkin.office.errors import DocumentError
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.service import DocumentService
from tests.office.test_export_policy import _request, _validated_draft


def test_directory_sync_failure_retains_recoverable_publication(
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

    # Then: published bytes and exact rollback authority remain durable.
    assert caught.value.retryable is True
    assert destination.read_bytes() == b"new validated bytes"
    backup_root = service.home / "artifacts" / "export-backups"
    backups = tuple(backup_root.glob("*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original


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

    # Then: published bytes and a durable recovery record remain available.
    assert caught.value.retryable is True
    assert destination.read_bytes() == b"new validated bytes"
    backups = tuple((service.home / "artifacts" / "export-backups").glob("*.bak"))
    transactions = tuple((service.home / "artifacts" / "export-journal").glob("*.json"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    assert len(transactions) == 1
    transaction = json.loads(transactions[0].read_text(encoding="utf-8"))
    assert transaction["authority_digest"] == transactions[0].stem
    assert transaction["authority_source_sha256"] == transaction["source_sha256"]

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


def test_existing_rollback_recovers_after_late_directory_sync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service, "new validated bytes")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    original = b"caller original before rollback sync"
    _ = destination.write_bytes(original)
    runner = DocumentServiceRunner(service, export_root=caller)
    receipt = runner.export(
        artifact=artifact,
        request=_request(destination, overwrite_approved=True),
    )
    real_sync = export_policy.sync_directory
    destination_syncs = 0

    def fail_second_destination_sync(
        path: Path,
        identity: tuple[int, int],
    ) -> None:
        nonlocal destination_syncs
        if path == caller:
            destination_syncs += 1
            if destination_syncs == 2:
                raise OSError(errno.EIO, "injected late rollback fsync failure")
        real_sync(path, identity)

    monkeypatch.setattr(
        export_policy,
        "sync_directory",
        fail_second_destination_sync,
    )

    with pytest.raises(DocumentError):
        _ = runner.rollback_export(receipt)
    assert destination.read_bytes() == original

    monkeypatch.setattr(export_policy, "sync_directory", real_sync)
    recovered = runner.rollback_export(receipt)

    assert recovered["restored"] is True
    assert destination.read_bytes() == original


def test_v1_overwrite_rollback_upgrades_authority_before_restore(
    tmp_path: Path,
) -> None:
    # Given: a legacy rolling-back checkpoint and receipt for an approved overwrite.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service, "new validated bytes")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    original = b"caller original before legacy rollback"
    _ = destination.write_bytes(original)
    runner = DocumentServiceRunner(service, export_root=caller)
    receipt = runner.export(
        artifact=artifact,
        request=_request(destination, overwrite_approved=True),
    )
    journal_path = next(
        (service.home / "artifacts" / "export-journal").glob("*.json")
    )
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    record["version"] = 1
    record["phase"] = "rolling_back"
    del record["authority_digest"]
    del record["authority_source_sha256"]
    del record["receipt_authenticated"]
    del record["receipt_issued_at"]
    del record["receipt_expires_at"]
    del record["receipt_hmac"]
    journal_path.write_text(json.dumps(record), encoding="utf-8")
    legacy_receipt = dict(receipt)
    del legacy_receipt["authority_digest"]
    del legacy_receipt["authority_source_sha256"]
    del legacy_receipt["overwrite_approved"]
    del legacy_receipt["issued_at"]
    del legacy_receipt["expires_at"]
    del legacy_receipt["receipt_hmac"]
    # When: rollback presents unauthenticated V1 authority.
    with pytest.raises(DocumentError, match="legacy unsigned rollback"):
        _ = DocumentServiceRunner(
            service,
            export_root=caller,
        ).rollback_export(legacy_receipt)

    # Then: legacy rollback fails closed without restoring attacker-selected bytes.
    assert destination.read_text(encoding="utf-8") == "new validated bytes"


def test_rollback_rejects_tampered_staging_before_restore(
    tmp_path: Path,
) -> None:
    # Given: a committed overwrite whose rollback staging path was changed.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service, "new validated bytes")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    original = b"caller original before staging tamper"
    _ = destination.write_bytes(original)
    runner = DocumentServiceRunner(service, export_root=caller)
    receipt = runner.export(
        artifact=artifact,
        request=_request(destination, overwrite_approved=True),
    )
    journal_path = next(
        (service.home / "artifacts" / "export-journal").glob("*.json")
    )
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    record["staging"] = str(caller / "unauthorized-staging.txt")
    journal_path.write_text(json.dumps(record), encoding="utf-8")

    # When: rollback uses the otherwise valid receipt.
    with pytest.raises(DocumentError) as caught:
        _ = runner.rollback_export(receipt)

    # Then: path identity fails before the exported destination changes.
    assert caught.value.code.value == "PERMISSION_DENIED"
    assert destination.read_text(encoding="utf-8") == "new validated bytes"
    assert not (caller / "unauthorized-staging.txt.rollback").exists()


def test_rollback_rejects_journal_filename_identity_mismatch(
    tmp_path: Path,
) -> None:
    # Given: a committed transaction stored under a different journal identity.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service, "new validated bytes")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    original = b"caller original before journal rename"
    _ = destination.write_bytes(original)
    runner = DocumentServiceRunner(service, export_root=caller)
    receipt = runner.export(
        artifact=artifact,
        request=_request(destination, overwrite_approved=True),
    )
    journal_path = next(
        (service.home / "artifacts" / "export-journal").glob("*.json")
    )
    renamed = journal_path.with_name(f"{'f' * 64}.json")
    _ = journal_path.rename(renamed)

    # When: rollback searches for the receipt token.
    with pytest.raises(DocumentError) as caught:
        _ = runner.rollback_export(receipt)

    # Then: durable path identity fails before mutation.
    assert caught.value.code.value == "PRECONDITION_FAILED"
    assert destination.read_text(encoding="utf-8") == "new validated bytes"


def test_rollback_without_durable_journal_cannot_delete_matching_file(
    tmp_path: Path,
) -> None:
    # Given: a forged legacy receipt describes an existing allowlisted file.
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    victim = caller / "victim.txt"
    payload = b"forged receipt target"
    _ = victim.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    receipt: dict[str, object] = {
        "rollback_token": uuid.uuid4().hex,
        "path": str(victim),
        "source_sha256": digest,
        "output_sha256": digest,
        "operations": [],
        "actor": "attacker",
        "proposal_digest": "forged",
        "destination_existed": False,
        "destination_sha256": None,
    }

    # When: rollback has no durable transaction matching the random token.
    with pytest.raises(DocumentError) as caught:
        _ = DocumentServiceRunner(
            service,
            export_root=caller,
        ).rollback_export(receipt)

    # Then: missing authority fails closed and the victim remains exact.
    assert caught.value.code.value == "PERMISSION_DENIED"
    assert victim.read_bytes() == payload


def test_rollback_rejects_matching_temporary_symlink(
    tmp_path: Path,
) -> None:
    # Given: rollback temporary staging is a symlink to matching backup bytes.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service, "new validated bytes")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    original = b"caller original before rollback symlink"
    _ = destination.write_bytes(original)
    runner = DocumentServiceRunner(service, export_root=caller)
    receipt = runner.export(
        artifact=artifact,
        request=_request(destination, overwrite_approved=True),
    )
    journal_path = next(
        (service.home / "artifacts" / "export-journal").glob("*.json")
    )
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    staging = Path(record["staging"])
    backup = Path(record["backup"])
    temporary = staging.with_name(f"{staging.name}.rollback")
    temporary.symlink_to(backup)

    # When: rollback sees matching bytes through the symlink.
    with pytest.raises(DocumentError):
        _ = runner.rollback_export(receipt)

    # Then: the approved destination remains a regular file with exported bytes.
    assert not destination.is_symlink()
    assert destination.read_text(encoding="utf-8") == "new validated bytes"


def test_rollback_rejects_temporary_swapped_after_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: rollback temporary becomes a matching symlink after its hash returns.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service, "new validated bytes")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    original = b"caller original before rollback hash swap"
    _ = destination.write_bytes(original)
    runner = DocumentServiceRunner(service, export_root=caller)
    receipt = runner.export(
        artifact=artifact,
        request=_request(destination, overwrite_approved=True),
    )
    real_hash = export_rollback_existing.current_hash

    def swap_after_hash(path: Path, stage: str = "rollback") -> str | None:
        digest = real_hash(path, stage)
        if path.name.endswith(".rollback"):
            journal_path = next(
                (service.home / "artifacts" / "export-journal").glob("*.json")
            )
            record = json.loads(journal_path.read_text(encoding="utf-8"))
            path.unlink()
            path.symlink_to(Path(record["backup"]))
        return digest

    monkeypatch.setattr(
        export_rollback_existing,
        "current_hash",
        swap_after_hash,
    )

    # When: rollback reaches replacement after hashing the temporary.
    with pytest.raises(DocumentError):
        _ = runner.rollback_export(receipt)

    # Then: the changed inode is not installed as the destination.
    assert not destination.is_symlink()
    assert destination.read_text(encoding="utf-8") == "new validated bytes"


def test_atomic_sync_compensation_keeps_export_resumable(
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

    monkeypatch.setattr(export_policy, "sync_directory", fail_commit_sync)
    request = _request(destination, overwrite_approved=True)

    # When: publication durability fails and atomic compensation restores prior bytes.
    with pytest.raises(DocumentError) as caught:
        _ = DocumentServiceRunner(service, export_root=caller).export(
            artifact=artifact, request=request
        )
    assert caught.value.retryable is True
    monkeypatch.setattr(export_policy, "sync_directory", real_sync)

    # Then: a fresh runner recognizes completed compensation and safely commits once.
    receipt = DocumentServiceRunner(service, export_root=caller).export(
        artifact=artifact, request=request
    )
    assert destination.read_text(encoding="utf-8") == "new validated bytes"
    rollback = DocumentServiceRunner(service, export_root=caller).rollback_export(receipt)
    assert rollback["restored"] is True
    assert destination.read_bytes() == original
