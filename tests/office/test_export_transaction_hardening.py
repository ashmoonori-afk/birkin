from __future__ import annotations

import datetime as dt
import os
import stat
import threading
from pathlib import Path

import pytest

from birkin import store
from birkin.office import export_atomic_publish, receipt_auth
from birkin.office.errors import (
    DocumentError,
    DocumentErrorCode,
)
from birkin.office.export_destination_lock import destination_lock_path
from birkin.office.export_policy import ExportRequest
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.service import DocumentService
from birkin.office.service_types import ArtifactRef
from birkin.office.service_workspace import DocumentWorkspace


def _draft(service: DocumentService, content: str) -> ArtifactRef:
    workspace = DocumentWorkspace(service.home)
    output = workspace.output_path("validated.txt", ".txt")

    def write(target: Path) -> None:
        _ = target.write_text(content, encoding="utf-8")

    _ = workspace.atomic_publish(output, write)
    return workspace.artifact(output)


def _request(destination: Path, *, overwrite: bool = True) -> ExportRequest:
    return ExportRequest(
        destination=destination,
        actor="reviewer:one",
        proposal_digest="proposal-sha256",
        operations=({"operation": "replace_text", "value": "approved"},),
        overwrite_approved=overwrite,
    )


def _fixture(
    tmp_path: Path,
    content: str = "new validated bytes",
) -> tuple[DocumentService, ArtifactRef, Path]:
    service = DocumentService(tmp_path / "office-home")
    artifact = _draft(service, content)
    caller = tmp_path / "caller"
    caller.mkdir()
    return service, artifact, caller


def _helpers(caller: Path) -> list[str]:
    # POSIX retirement moves bytes into a `.birkin-retire` quarantine instead of
    # unlinking them (documented in docs/office-support.md), so that directory is
    # an outcome of a successful retire, not a leftover export helper.
    return sorted(
        entry.name
        for entry in caller.iterdir()
        if entry.name.startswith(".") and entry.name != ".birkin-retire"
    )


def test_read_only_destination_commits_and_retires_checkpoint(
    tmp_path: Path,
) -> None:
    service, artifact, caller = _fixture(tmp_path)
    destination = caller / "result.txt"
    _ = destination.write_bytes(b"caller original")
    os.chmod(destination, stat.S_IREAD)
    runner = DocumentServiceRunner(service, export_root=caller)

    receipt = runner.export(artifact=artifact, request=_request(destination))

    assert receipt["rollback_token"]
    assert destination.read_bytes() == b"new validated bytes"
    assert _helpers(caller) == []


def test_empty_destination_returns_after_failed_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, artifact, caller = _fixture(tmp_path)
    destination = caller / "empty.txt"
    _ = destination.write_bytes(b"")
    runner = DocumentServiceRunner(service, export_root=caller)

    def fail(descriptor: int, target: Path) -> tuple[int, int]:
        del descriptor, target
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "export",
            "injected publication failure",
        )

    monkeypatch.setattr(
        export_atomic_publish,
        "publication_from_descriptor",
        fail,
    )
    with pytest.raises(DocumentError):
        _ = runner.export(artifact=artifact, request=_request(destination))

    assert destination.is_file()
    assert destination.read_bytes() == b""
    assert not [name for name in _helpers(caller) if name.endswith(".displaced")]


def test_contended_destination_lock_reports_retryable_failure(
    tmp_path: Path,
) -> None:
    service, artifact, caller = _fixture(tmp_path)
    destination = caller / "new.txt"
    runner = DocumentServiceRunner(service, export_root=caller)
    lock_path = destination_lock_path(
        service.home / "artifacts" / "export-backups",
        destination,
    )
    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with store.file_lock(lock_path, timeout=1):
            held.set()
            _ = release.wait(20)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert held.wait(10)
        with pytest.raises(DocumentError) as failure:
            _ = runner.export(artifact=artifact, request=_request(destination))
    finally:
        release.set()
        holder.join()

    assert failure.value.code is DocumentErrorCode.INTERNAL_ERROR
    assert failure.value.retryable
    assert not destination.exists()


def test_contended_rollback_lock_reports_retryable_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, artifact, caller = _fixture(tmp_path)
    destination = caller / "new.txt"
    runner = DocumentServiceRunner(service, export_root=caller)
    receipt = runner.export(artifact=artifact, request=_request(destination))

    def contended(path: Path, **_options: object) -> object:
        raise store.FileLockTimeout(f"timed out acquiring {path}")

    monkeypatch.setattr(store, "file_lock", contended)
    with pytest.raises(DocumentError) as failure:
        _ = runner.rollback_export(receipt)

    assert failure.value.code is DocumentErrorCode.INTERNAL_ERROR
    assert failure.value.retryable
    assert failure.value.stage == "rollback"


def test_prepared_transaction_resumes_after_retention_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, artifact, caller = _fixture(tmp_path)
    destination = caller / "new.txt"
    runner = DocumentServiceRunner(service, export_root=caller)
    request = _request(destination)

    def fail(descriptor: int, target: Path) -> tuple[int, int]:
        del descriptor, target
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "export",
            "injected publication failure",
        )

    monkeypatch.setattr(
        export_atomic_publish,
        "publication_from_descriptor",
        fail,
    )
    with pytest.raises(DocumentError):
        _ = runner.export(artifact=artifact, request=request)
    monkeypatch.undo()

    real_datetime = receipt_auth.datetime

    class Future(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
            return real_datetime.now(tz) + dt.timedelta(days=31)

    monkeypatch.setattr(receipt_auth, "datetime", Future)
    resumed = runner.export(artifact=artifact, request=request)

    assert resumed["rollback_token"]
    assert destination.read_text(encoding="utf-8") == "new validated bytes"


@pytest.mark.skipif(
    os.name != "nt",
    reason="handle-bound publication temporaries are Windows only",
)
def test_failed_windows_publication_leaves_no_temporary(
    tmp_path: Path,
) -> None:
    from birkin.office.export_inode_publish import publish_open_file

    source = tmp_path / "source.txt"
    _ = source.write_bytes(b"validated")
    destination = tmp_path / "destination.txt"
    _ = destination.write_bytes(b"occupied")
    descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        with pytest.raises(FileExistsError):
            _ = publish_open_file(descriptor, destination)
    finally:
        os.close(descriptor)

    assert _helpers(tmp_path) == []


@pytest.mark.skipif(
    os.path.normcase("A") == "A",
    reason="path case only folds on case-insensitive platforms",
)
def test_destination_lock_folds_path_case(tmp_path: Path) -> None:
    backup_root = tmp_path / "artifacts" / "export-backups"

    assert destination_lock_path(
        backup_root, Path("C:/Exports/Report.docx")
    ) == destination_lock_path(backup_root, Path("c:/exports/report.docx"))
