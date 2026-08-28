"""Destination-scoped serialization shared by export and rollback."""

from __future__ import annotations

import hashlib
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from birkin import store

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
    key = hashlib.sha256(str(destination).encode("utf-8")).hexdigest()
    return root / key


@contextmanager
def export_transaction_lock(
    backup_root: Path,
    destination: Path,
    journal: ExportJournal,
    transaction_id: str,
) -> Generator[None]:
    with store.file_lock(destination_lock_path(backup_root, destination)):
        with store.file_lock(journal.path_for(transaction_id)):
            yield
