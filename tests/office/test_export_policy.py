from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.export_policy import ExportRequest
from birkin.office.job_runner import DocumentServiceRunner
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
    assert sorted(path.name for path in caller_folder.iterdir()) == [destination.name]


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

    # Then: the destination is identical to before and no helper files remain.
    assert destination.read_bytes() == original
    assert rollback["destination_sha256"] == hashlib.sha256(original).hexdigest()
    assert rollback["restored"] is True
    assert sorted(path.name for path in caller_folder.iterdir()) == [destination.name]
    backup_root = service.home / "artifacts" / "export-backups"
    assert not backup_root.exists() or not tuple(backup_root.iterdir())


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

    # Then: the caller's original bytes are restored without backup residue.
    assert rollback["restored"] is True
    assert destination.read_bytes() == original
    backup_root = service.home / "artifacts" / "export-backups"
    assert not tuple(backup_root.iterdir())


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
    assert not tuple(caller_folder.iterdir())


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
