"""Destination-scoped serialization shared by export and rollback."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from birkin import store

from .export_io import recovery_error
from .export_journal import ExportJournal
from .journal_record import journal_root

_STAGE = "office_export_lock"


def destination_lock_path(
    backup_root: Path,
    destination: Path,
) -> Path:
    root = journal_root(
        backup_root.parent / "export-locks",
        _STAGE,
    )
    key = hashlib.sha256(
        os.path.normcase(str(destination)).encode("utf-8")
    ).hexdigest()
    return root / key


@contextmanager
def held_export_lock(
    path: Path,
    message: str,
    stage: str = "export",
) -> Generator[None]:
    """Hold one export lock and report contention as a retryable failure."""
    try:
        with store.file_lock(path):
            yield
    except store.FileLockTimeout as exc:
        raise recovery_error(message, stage) from exc


@contextmanager
def export_transaction_lock(
    backup_root: Path,
    destination: Path,
    journal: ExportJournal,
    transaction_id: str,
) -> Generator[None]:
    with held_export_lock(
        destination_lock_path(backup_root, destination),
        "export destination is locked by another transaction",
    ):
        with held_export_lock(
            journal.path_for(transaction_id),
            "export transaction journal is locked by another transaction",
        ):
            yield
