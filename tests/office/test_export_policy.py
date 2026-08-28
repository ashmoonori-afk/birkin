from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.export_policy import ExportRequest
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.receipt_auth import sign_receipt
from birkin.office.service import DocumentService
from birkin.office.service_types import ArtifactRef
from birkin.office.service_workspace import DocumentWorkspace


def _validated_draft(service: DocumentService, payload: str = "validated result") -> ArtifactRef:
    workspace = DocumentWorkspace(service.home)
    output = workspace.output_path("validated.txt", ".txt")
    def write(target: Path) -> None:
        _ = target.write_text(payload, encoding="utf-8")

    _ = workspace.atomic_publish(output, write)
    return workspace.artifact(output)


def _request(destination: Path, *, overwrite_approved: bool = False) -> ExportRequest:
    return ExportRequest(
        destination=destination,
        actor="reviewer:one",
        proposal_digest="proposal-sha256",
        operations=({"operation": "replace_text", "value": "approved"},),
        overwrite_approved=overwrite_approved,
    )


def _assert_safe_helpers(
    folder: Path,
    destination: Path | None,
    published: bytes,
) -> None:
    helpers = tuple(
        path
        for path in folder.iterdir()
        if destination is None or path != destination
    )
    for path in helpers:
        if path.name == ".birkin-retire":
            mode = path.stat().st_mode
            assert stat.S_ISDIR(mode)
            assert not mode & (stat.S_IWGRP | stat.S_IWOTH)
            assert all(entry.is_file() for entry in path.iterdir())
        else:
            assert path.name.startswith(".birkin-export-")
            assert path.read_bytes() in {b"", published}


def _assert_retired_backups(backup_root: Path) -> None:
    entries = tuple(backup_root.iterdir())
    assert len(entries) <= 1
    if entries:
        quarantine = entries[0]
        assert quarantine.name == ".birkin-retire"
        mode = quarantine.stat().st_mode
        assert stat.S_ISDIR(mode)
        assert not mode & (stat.S_IWGRP | stat.S_IWOTH)
        assert all(entry.is_file() for entry in quarantine.iterdir())


def test_export_places_copy_at_exact_caller_path_and_preserves_validated_draft(
    tmp_path: Path,
) -> None:
    # Given: a validated managed draft and an allowlisted caller folder.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service)
    source = Path(str(artifact["uri"]))
    source_before = source.read_bytes()
    caller_folder = tmp_path / "caller-output"
    caller_folder.mkdir()
    destination = caller_folder / "고객 전달본.txt"
    runner = DocumentServiceRunner(service, export_root=caller_folder)

    # When: the runner exports to the caller's exact destination.
    receipt = runner.export(artifact=artifact, request=_request(destination))

    # Then: the draft remains internal and the complete receipt binds both copies.
    digest = hashlib.sha256(source_before).hexdigest()
    assert Path(str(receipt["path"])) == destination
    assert destination.read_bytes() == source_before
    assert source.read_bytes() == source_before
    assert source.parent == service.home / "artifacts" / "drafts"
    assert receipt["source_sha256"] == digest
    assert receipt["output_sha256"] == digest
    assert receipt["operations"] == [
        {"operation": "replace_text", "value": "approved"}
    ]
    assert receipt["actor"] == "reviewer:one"
    assert receipt["proposal_digest"] == "proposal-sha256"
    _assert_safe_helpers(caller_folder, destination, source_before)


def test_export_denies_destination_outside_allowlisted_root_without_writing(
    tmp_path: Path,
) -> None:
    # Given: a valid draft, one allowlisted folder, and an outside destination.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service)
    caller_folder = tmp_path / "caller-output"
    caller_folder.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    before = tuple(tmp_path.rglob("*"))
    runner = DocumentServiceRunner(service, export_root=caller_folder)

    # When: export is requested outside the allowlist.
    with pytest.raises(DocumentError) as caught:
        _ = runner.export(
            artifact=artifact,
            request=_request(outside / "escaped.txt"),
        )

    # Then: policy denies the request before any filesystem mutation.
    assert caught.value.code is DocumentErrorCode.PERMISSION_DENIED
    assert tuple(tmp_path.rglob("*")) == before


def test_existing_destination_requires_separate_overwrite_approval(
    tmp_path: Path,
) -> None:
    # Given: the caller's requested filename already exists.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service)
    caller_folder = tmp_path / "caller-output"
    caller_folder.mkdir()
    destination = caller_folder / "result.txt"
    _ = destination.write_bytes(b"caller original")
    before = tuple(caller_folder.iterdir())
    runner = DocumentServiceRunner(service, export_root=caller_folder)

    # When: export has proposal approval but no overwrite approval.
    with pytest.raises(DocumentError) as caught:
        _ = runner.export(artifact=artifact, request=_request(destination))

    # Then: the existing bytes and directory entries are unchanged.
    assert caught.value.code is DocumentErrorCode.OUTPUT_EXISTS
    assert destination.read_bytes() == b"caller original"
    assert tuple(caller_folder.iterdir()) == before


def test_rollback_restores_overwritten_destination_byte_for_byte_without_residue(
    tmp_path: Path,
) -> None:
    # Given: overwrite is separately approved for an existing caller file.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service, "new validated bytes")
    caller_folder = tmp_path / "caller-output"
    caller_folder.mkdir()
    destination = caller_folder / "result.txt"
    original = b"caller original\x00bytes"
    _ = destination.write_bytes(original)
    runner = DocumentServiceRunner(service, export_root=caller_folder)

    # When: the approved export is rolled back.
    receipt = runner.export(
        artifact=artifact,
        request=_request(destination, overwrite_approved=True),
    )
    rollback = runner.rollback_export(receipt)

    # Then: the destination is identical and backup bytes are retired.
    assert destination.read_bytes() == original
    assert rollback["destination_sha256"] == hashlib.sha256(original).hexdigest()
    assert rollback["restored"] is True
    _assert_safe_helpers(
        caller_folder,
        destination,
        b"new validated bytes",
    )
    backup_root = service.home / "artifacts" / "export-backups"
    _assert_retired_backups(backup_root)


def test_export_receipt_rolls_back_after_runner_restart(tmp_path: Path) -> None:
    # Given: an overwritten destination and only the durable public export receipt.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service, "new validated bytes")
    caller_folder = tmp_path / "caller-output"
    caller_folder.mkdir()
    destination = caller_folder / "result.txt"
    original = b"caller original before restart"
    _ = destination.write_bytes(original)
    receipt = DocumentServiceRunner(service, export_root=caller_folder).export(
        artifact=artifact,
        request=_request(destination, overwrite_approved=True),
    )

    # When: a fresh runner restores the rollback authority from the receipt.
    rollback = DocumentServiceRunner(
        service, export_root=caller_folder
    ).rollback_export(receipt)

    # Then: the caller's original bytes are restored and backup bytes retired.
    assert rollback["restored"] is True
    assert destination.read_bytes() == original
    backup_root = service.home / "artifacts" / "export-backups"
    _assert_retired_backups(backup_root)


def test_rollback_removes_destination_that_did_not_exist_before_export(
    tmp_path: Path,
) -> None:
    # Given: a new caller destination.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service)
    caller_folder = tmp_path / "caller-output"
    caller_folder.mkdir()
    destination = caller_folder / "new.txt"
    runner = DocumentServiceRunner(service, export_root=caller_folder)

    # When: export is rolled back.
    receipt = runner.export(artifact=artifact, request=_request(destination))
    rollback = runner.rollback_export(receipt)

    # Then: the caller folder returns to its exact prior contents.
    assert rollback["restored"] is False
    assert not destination.exists()
    _assert_safe_helpers(
        caller_folder,
        None,
        b"validated result",
    )


def test_identical_export_can_run_after_rollback(
    tmp_path: Path,
) -> None:
    # Given: one approved export was rolled back completely.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service, "repeatable export")
    caller_folder = tmp_path / "caller-output"
    caller_folder.mkdir()
    destination = caller_folder / "result.txt"
    _ = destination.write_text("original", encoding="utf-8")
    runner = DocumentServiceRunner(service, export_root=caller_folder)
    request = _request(destination, overwrite_approved=True)
    first = runner.export(artifact=artifact, request=request)
    _ = runner.rollback_export(first)

    # When: the same authority exports the same validated bytes again.
    second = runner.export(artifact=artifact, request=request)

    # Then: the renewed transaction publishes and remains rollback-capable.
    assert destination.read_text(encoding="utf-8") == "repeatable export"
    assert second["rollback_token"] != first["rollback_token"]
    _ = runner.rollback_export(second)
    assert destination.read_text(encoding="utf-8") == "original"


def test_same_runner_rollback_rejects_tampered_receipt_authority(
    tmp_path: Path,
) -> None:
    # Given: a current runner caches the exact export receipt.
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service)
    caller_folder = tmp_path / "caller-output"
    caller_folder.mkdir()
    destination = caller_folder / "new.txt"
    runner = DocumentServiceRunner(service, export_root=caller_folder)
    receipt = runner.export(artifact=artifact, request=_request(destination))
    tampered = {**receipt, "actor": "attacker"}

    # When: the same token is presented with changed authority fields.
    with pytest.raises(DocumentError):
        _ = runner.rollback_export(tampered)

    # Then: cached authority does not bypass receipt validation.
    assert destination.read_text(encoding="utf-8") == "validated result"


def test_export_receipt_is_hmac_authenticated(
    tmp_path: Path,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service)
    caller_folder = tmp_path / "caller-output"
    caller_folder.mkdir()
    destination = caller_folder / "new.txt"
    receipt = DocumentServiceRunner(
        service,
        export_root=caller_folder,
    ).export(
        artifact=artifact,
        request=_request(destination),
    )

    assert len(receipt["receipt_hmac"]) == 64
    assert receipt["issued_at"].endswith("Z")
    assert receipt["expires_at"].endswith("Z")
    if os.name == "posix":
        assert (
            service.home.joinpath("receipt_hmac_key").stat().st_mode & 0o777
            == 0o600
        )


def test_fresh_runner_rejects_forged_receipt_hmac(
    tmp_path: Path,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service)
    caller_folder = tmp_path / "caller-output"
    caller_folder.mkdir()
    destination = caller_folder / "new.txt"
    receipt = DocumentServiceRunner(
        service,
        export_root=caller_folder,
    ).export(
        artifact=artifact,
        request=_request(destination),
    )
    forged = {**receipt, "actor": "forged-actor"}

    with pytest.raises(DocumentError, match="authentication"):
        _ = DocumentServiceRunner(
            service,
            export_root=caller_folder,
        ).rollback_export(forged)

    assert destination.read_text(encoding="utf-8") == "validated result"


def test_rollback_rejects_expired_receipt(
    tmp_path: Path,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    artifact = _validated_draft(service)
    caller_folder = tmp_path / "caller-output"
    caller_folder.mkdir()
    destination = caller_folder / "new.txt"
    receipt = DocumentServiceRunner(
        service,
        export_root=caller_folder,
    ).export(
        artifact=artifact,
        request=_request(destination),
    )
    expired = {
        **receipt,
        "issued_at": "2020-01-01T00:00:00Z",
        "expires_at": "2020-01-02T00:00:00Z",
    }
    expired["receipt_hmac"] = sign_receipt(
        {
            key: value
            for key, value in expired.items()
            if key != "receipt_hmac"
        },
        service.home,
    )

    with pytest.raises(DocumentError, match="retention window expired"):
        _ = DocumentServiceRunner(
            service,
            export_root=caller_folder,
        ).rollback_export(expired)

    assert destination.read_text(encoding="utf-8") == "validated result"
