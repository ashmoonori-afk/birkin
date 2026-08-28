"""Exact filesystem primitives for export transaction recovery."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path

from .artifact_snapshot import SnapshotPath
from .errors import DocumentError, DocumentErrorCode
from .export_journal import ExportTransaction

DirectorySync = Callable[[Path, tuple[int, int]], None]


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def recovery_error(message: str, stage: str = "export") -> DocumentError:
    return DocumentError(
        DocumentErrorCode.INTERNAL_ERROR,
        stage,
        message,
        retryable=True,
        details={"reason": "recovery_required"},
    )


def regular_file_identity(path: Path, stage: str = "export") -> tuple[int, int]:
    try:
        if os.name == "nt":
            from .path_identity import regular_path_identity

            return regular_path_identity(path)
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise recovery_error("export helper identity is unavailable", stage) from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise recovery_error("export helper must remain a regular file", stage)
    return metadata.st_dev, metadata.st_ino


def copy_exact(source: Path | SnapshotPath, target: Path) -> None:
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        source_descriptor = os.open(source, os.O_RDONLY)
        with os.fdopen(descriptor, "wb") as outgoing, os.fdopen(
            source_descriptor, "rb"
        ) as incoming:
            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
    except OSError:
        target.unlink(missing_ok=True)
        raise


def current_hash(path: Path, stage: str = "export") -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise DocumentError(
            DocumentErrorCode.PERMISSION_DENIED,
            stage,
            "export destination must remain a regular file",
        )
    return hash_file(path)


def reservation_bytes(transaction: ExportTransaction) -> bytes:
    return f"birkin-export-reservation:{transaction.rollback_token}".encode("ascii")


def reservation_hash(transaction: ExportTransaction) -> str:
    return hashlib.sha256(reservation_bytes(transaction)).hexdigest()
