from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from birkin.office import (
    export_atomic_publish,
    export_displacement_restore,
    export_rollback_state,
)
from birkin.office.artifact_snapshot import SnapshotPath
from birkin.office.errors import DocumentError
from birkin.office.export_commit import ExportCommit
from birkin.office.export_policy import ExportRequest
from birkin.office.export_journal import ExportTransaction
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.receipt_auth import sign_receipt
from birkin.office.service import DocumentService
from birkin.office.service_types import ArtifactRef
from birkin.office.service_workspace import DocumentWorkspace


class SimulatedCrash(BaseException):
    pass


def _draft(
    service: DocumentService,
    name: str,
    content: str,
) -> ArtifactRef:
    workspace = DocumentWorkspace(service.home)
    output = workspace.output_path(name, ".txt")

    def write(target: Path) -> None:
        _ = target.write_text(content, encoding="utf-8")

    _ = workspace.atomic_publish(output, write)
    return workspace.artifact(output)


def _request(destination: Path, actor: str) -> ExportRequest:
    return ExportRequest(
        destination=destination,
        actor=actor,
        proposal_digest=hashlib.sha256(actor.encode()).hexdigest(),
        operations=({"op": "replace", "value": actor},),
        overwrite_approved=True,
    )


def test_different_authorities_serialize_one_destination(
    tmp_path: Path,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    _ = destination.write_text("original", encoding="utf-8")
    artifacts = (
        _draft(service, "first.txt", "first"),
        _draft(service, "second.txt", "second"),
    )
    barrier = Barrier(2)

    def export(index: int) -> dict[str, object]:
        _ = barrier.wait(timeout=5)
        return dict(
            DocumentServiceRunner(service, export_root=caller).export(
                artifact=artifacts[index],
                request=_request(destination, f"actor:{index}"),
            )
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = tuple(pool.map(export, (0, 1)))

    final = destination.read_text(encoding="utf-8")
    last = next(
        receipt
        for receipt in receipts
        if receipt["output_sha256"]
        == hashlib.sha256(final.encode()).hexdigest()
    )
    first = next(receipt for receipt in receipts if receipt is not last)
    _ = DocumentServiceRunner(service, export_root=caller).rollback_export(last)
    assert destination.read_text(encoding="utf-8") != "original"
    _ = DocumentServiceRunner(service, export_root=caller).rollback_export(first)
    assert destination.read_text(encoding="utf-8") == "original"


def test_export_refuses_concurrent_destination_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    _ = destination.write_text("original", encoding="utf-8")
    artifact = _draft(service, "validated.txt", "validated")
    real_stage = ExportCommit.stage

    def write_after_stage(
        transaction: ExportTransaction,
        source: SnapshotPath,
    ) -> tuple[int, int]:
        identity = real_stage(transaction, source)
        _ = destination.write_text("concurrent", encoding="utf-8")
        return identity

    monkeypatch.setattr(
        ExportCommit,
        "stage",
        staticmethod(write_after_stage),
    )

    with pytest.raises(DocumentError, match="changed before atomic"):
        _ = DocumentServiceRunner(service, export_root=caller).export(
            artifact=artifact,
            request=_request(destination, "actor:export"),
        )

    assert destination.read_text(encoding="utf-8") == "concurrent"


def test_rollback_preserves_destination_recreated_after_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    artifact = _draft(service, "validated.txt", "validated")
    runner = DocumentServiceRunner(service, export_root=caller)
    receipt = runner.export(
        artifact=artifact,
        request=_request(destination, "actor:rollback"),
    )
    real_current_hash = export_rollback_state.destination_hash
    replaced = False

    def replace_after_hash(path: Path, stage: str = "export") -> str | None:
        nonlocal replaced
        result = real_current_hash(path, stage)
        if path == destination and not replaced:
            replaced = True
            _ = destination.write_text("concurrent", encoding="utf-8")
        return result

    monkeypatch.setattr(
        export_rollback_state,
        "destination_hash",
        replace_after_hash,
    )

    with pytest.raises(DocumentError, match="changed during deletion"):
        _ = runner.rollback_export(receipt)

    assert destination.read_text(encoding="utf-8") == "concurrent"


def test_export_does_not_publish_swapped_staging_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    _ = destination.write_text("original", encoding="utf-8")
    artifact = _draft(service, "validated.txt", "validated")
    attacker = caller / "attacker.txt"
    _ = attacker.write_text("attacker", encoding="utf-8")
    real_require = ExportCommit.require_destination_state

    def swap_after_final_check(
        transaction: ExportTransaction,
    ) -> None:
        real_require(transaction)
        transaction.staging.unlink()
        transaction.staging.symlink_to(attacker)

    monkeypatch.setattr(
        ExportCommit,
        "require_destination_state",
        staticmethod(swap_after_final_check),
    )

    with pytest.raises(DocumentError):
        _ = DocumentServiceRunner(service, export_root=caller).export(
            artifact=artifact,
            request=_request(destination, "actor:swap"),
        )

    assert not destination.is_symlink()
    assert destination.read_text(encoding="utf-8") == "original"


def test_export_does_not_publish_inode_swapped_inside_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    _ = destination.write_text("original", encoding="utf-8")
    artifact = _draft(service, "validated.txt", "validated")
    real_publish = export_atomic_publish.publication_from_descriptor
    swapped = False

    def swap_before_publish(
        source_descriptor: int,
        target: Path,
    ) -> tuple[int, int]:
        nonlocal swapped
        staging = next(
            path
            for path in caller.glob(".birkin-export-*")
            if not path.name.endswith(".displaced")
        )
        staging.unlink()
        _ = staging.write_text("attacker", encoding="utf-8")
        swapped = True
        return real_publish(source_descriptor, target)

    monkeypatch.setattr(
        export_atomic_publish,
        "publication_from_descriptor",
        swap_before_publish,
    )

    with pytest.raises(DocumentError) as captured:
        _ = DocumentServiceRunner(service, export_root=caller).export(
            artifact=artifact,
            request=_request(destination, "actor:link-swap"),
        )

    assert swapped is True
    assert captured.value.retryable is True
    assert destination.read_text(encoding="utf-8") == "validated"
    assert tuple(caller.glob("*.displaced"))


def test_export_compensation_defers_while_destination_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    _ = destination.write_text("original", encoding="utf-8")
    artifact = _draft(service, "validated.txt", "validated")
    real_publication = export_atomic_publish.publication_from_descriptor
    real_restore = export_displacement_restore.publish_open_file
    publication_swapped = False
    compensation_raced = False

    def replace_staging(
        descriptor: int,
        target: Path,
    ) -> tuple[int, int]:
        nonlocal publication_swapped
        staging = next(
            path
            for path in caller.glob(".birkin-export-*")
            if not path.name.endswith(".displaced")
        )
        staging.unlink()
        _ = staging.write_text("attacker", encoding="utf-8")
        publication_swapped = True
        return real_publication(descriptor, target)

    def recreate_before_restore(
        descriptor: int,
        target: Path,
    ) -> tuple[int, int]:
        nonlocal compensation_raced
        if target == destination:
            _ = destination.write_text("concurrent", encoding="utf-8")
            compensation_raced = True
        return real_restore(descriptor, target)

    monkeypatch.setattr(
        export_atomic_publish,
        "publication_from_descriptor",
        replace_staging,
    )
    monkeypatch.setattr(
        export_displacement_restore,
        "publish_open_file",
        recreate_before_restore,
    )

    with pytest.raises(DocumentError) as captured:
        _ = DocumentServiceRunner(service, export_root=caller).export(
            artifact=artifact,
            request=_request(destination, "actor:compensation-race"),
        )

    assert publication_swapped is True
    assert compensation_raced is False
    assert captured.value.retryable is True
    assert destination.read_text(encoding="utf-8") == "validated"
    assert tuple(caller.glob("*.displaced"))


def test_export_compensation_never_unlinks_replaced_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    _ = destination.write_text("original", encoding="utf-8")
    artifact = _draft(service, "validated.txt", "validated")
    real_publication = export_atomic_publish.publication_from_descriptor
    real_unlink = Path.unlink
    unlink_race_fired = False

    def replace_staging(
        descriptor: int,
        target: Path,
    ) -> tuple[int, int]:
        staging = next(
            path
            for path in caller.glob(".birkin-export-*")
            if not path.name.endswith(".displaced")
        )
        staging.unlink()
        _ = staging.write_text("attacker", encoding="utf-8")
        return real_publication(descriptor, target)

    def replace_before_unlink(
        path: Path,
        missing_ok: bool = False,
    ) -> None:
        nonlocal unlink_race_fired
        if path == destination:
            saved = caller / "saved-published.txt"
            path.rename(saved)
            _ = path.write_text("concurrent", encoding="utf-8")
            unlink_race_fired = True
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(
        export_atomic_publish,
        "publication_from_descriptor",
        replace_staging,
    )
    monkeypatch.setattr(Path, "unlink", replace_before_unlink)

    with pytest.raises(DocumentError) as captured:
        _ = DocumentServiceRunner(service, export_root=caller).export(
            artifact=artifact,
            request=_request(destination, "actor:unlink-race"),
        )

    assert unlink_race_fired is False
    assert captured.value.retryable is True
    assert destination.read_text(encoding="utf-8") == "validated"
    assert tuple(caller.glob("*.displaced"))


def test_export_preserves_write_after_final_destination_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    _ = destination.write_text("original", encoding="utf-8")
    artifact = _draft(service, "validated.txt", "validated")
    real_require = ExportCommit.require_destination_state

    def write_after_final_check(
        transaction: ExportTransaction,
    ) -> None:
        real_require(transaction)
        _ = destination.write_text("concurrent", encoding="utf-8")

    monkeypatch.setattr(
        ExportCommit,
        "require_destination_state",
        staticmethod(write_after_final_check),
    )

    with pytest.raises(DocumentError, match="atomic displacement"):
        _ = DocumentServiceRunner(service, export_root=caller).export(
            artifact=artifact,
            request=_request(destination, "actor:final-race"),
        )

    assert destination.read_text(encoding="utf-8") == "concurrent"


def test_export_recovers_crash_after_atomic_displacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "result.txt"
    _ = destination.write_text("original", encoding="utf-8")
    artifact = _draft(service, "validated.txt", "validated")
    runner = DocumentServiceRunner(service, export_root=caller)
    request = _request(destination, "actor:crash")
    _ = sign_receipt({"probe": "initialize-key"}, service.home)
    real_publish = export_atomic_publish.publication_from_descriptor

    def crash_before_publish(
        source_descriptor: int,
        target: Path,
    ) -> tuple[int, int]:
        del source_descriptor, target
        raise SimulatedCrash

    monkeypatch.setattr(
        export_atomic_publish,
        "publication_from_descriptor",
        crash_before_publish,
    )
    with pytest.raises(SimulatedCrash):
        _ = runner.export(artifact=artifact, request=request)
    assert not destination.exists()
    assert tuple(caller.glob("*.displaced"))

    monkeypatch.setattr(
        export_atomic_publish,
        "publication_from_descriptor",
        real_publish,
    )
    receipt = runner.export(artifact=artifact, request=request)
    assert destination.read_text(encoding="utf-8") == "validated"
    _ = runner.rollback_export(receipt)
    assert destination.read_text(encoding="utf-8") == "original"


def test_rollback_cleanup_preserves_other_transaction_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    destinations = (caller / "first.txt", caller / "second.txt")
    _ = destinations[0].write_text("first original", encoding="utf-8")
    _ = destinations[1].write_text("second original", encoding="utf-8")
    runner = DocumentServiceRunner(service, export_root=caller)
    receipts = (
        runner.export(
            artifact=_draft(service, "first-new.txt", "first validated"),
            request=_request(destinations[0], "actor:first"),
        ),
        runner.export(
            artifact=_draft(service, "second-new.txt", "second validated"),
            request=_request(destinations[1], "actor:second"),
        ),
    )
    backup_root = service.home / "artifacts" / "export-backups"
    backups = tuple(
        backup_root / f"{receipt['rollback_token']}.bak"
        for receipt in receipts
    )
    saved_first = backups[0].with_name("saved-first.bak")
    real_unlink = Path.unlink
    race_fired = False

    def swap_before_unlink(
        path: Path,
        missing_ok: bool = False,
    ) -> None:
        nonlocal race_fired
        if path == backups[0]:
            backups[0].rename(saved_first)
            backups[1].rename(backups[0])
            race_fired = True
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", swap_before_unlink)

    first_rollback = runner.rollback_export(receipts[0])
    second_rollback = runner.rollback_export(receipts[1])

    assert race_fired is False
    assert first_rollback["restored"] is True
    assert second_rollback["restored"] is True
    assert destinations[0].read_text(encoding="utf-8") == "first original"
    assert destinations[1].read_text(encoding="utf-8") == "second original"


def test_new_destination_rollback_preserves_occupied_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "new.txt"
    runner = DocumentServiceRunner(service, export_root=caller)
    receipt = runner.export(
        artifact=_draft(service, "new.txt", "validated"),
        request=_request(destination, "actor:new"),
    )
    real_move = export_rollback_state.move_no_replace
    checkpoint: Path | None = None

    def occupy_before_move(source: Path, target: Path) -> None:
        nonlocal checkpoint
        target.write_text("concurrent checkpoint", encoding="utf-8")
        checkpoint = target
        real_move(source, target)

    monkeypatch.setattr(
        export_rollback_state,
        "move_no_replace",
        occupy_before_move,
    )

    with pytest.raises(DocumentError) as captured:
        _ = runner.rollback_export(receipt)

    assert captured.value.retryable is True
    assert destination.read_text(encoding="utf-8") == "validated"
    assert checkpoint is not None
    assert checkpoint.read_text(encoding="utf-8") == "concurrent checkpoint"


@pytest.mark.skipif(os.name != "nt", reason="Windows CRT binary-mode contract")
def test_windows_binary_export_and_rollback_preserve_control_bytes(
    tmp_path: Path,
) -> None:
    service = DocumentService(tmp_path / "office-home")
    caller = tmp_path / "caller"
    caller.mkdir()
    destination = caller / "binary.txt"
    original = b"original\r\n\x1a bytes"
    _ = destination.write_bytes(original)
    artifact = _draft(service, "validated.txt", "validated\r\n\x1a bytes")
    expected = Path(str(artifact["uri"])).read_bytes()
    runner = DocumentServiceRunner(service, export_root=caller)

    receipt = runner.export(
        artifact=artifact,
        request=_request(destination, "actor:windows-binary"),
    )

    assert destination.read_bytes() == expected
    _ = runner.rollback_export(receipt)
    assert destination.read_bytes() == original
