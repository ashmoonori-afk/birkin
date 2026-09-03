"""Retry-safe compensation without deleting caller pathnames."""

from __future__ import annotations

from pathlib import Path

from .errors import DocumentError
from .export_displacement_restore import restore_displaced
from .export_io import (
    EMPTY_SHA256,
    DirectorySync,
    current_hash,
    recovery_error,
    regular_file_identity,
)
from .export_journal_record import ExportTransaction


def compensate_export(
    transaction: ExportTransaction,
    checkpoint: Path,
    expected_sha256: str,
    sync_directory: DirectorySync,
) -> None:
    try:
        if (
            checkpoint.is_file()
            and checkpoint.stat().st_size == 0
            and expected_sha256 != EMPTY_SHA256
        ):
            _sync_parent(transaction, sync_directory)
            return
        if not checkpoint.exists() and not checkpoint.is_symlink():
            if (
                not transaction.destination.exists()
                and not transaction.destination.is_symlink()
            ):
                raise recovery_error(
                    "atomic export compensation source is unavailable"
                )
            _sync_parent(transaction, sync_directory)
            return
        if (
            transaction.destination.exists()
            or transaction.destination.is_symlink()
        ):
            if (
                not transaction.destination.is_symlink()
                and not checkpoint.is_symlink()
                and regular_file_identity(transaction.destination)
                == regular_file_identity(checkpoint)
                and current_hash(transaction.destination)
                == expected_sha256
            ):
                _sync_parent(transaction, sync_directory)
                return
            raise recovery_error(
                "atomic export compensation is waiting for destination recovery"
            )
        restore_displaced(
            checkpoint,
            transaction.destination,
            expected_sha256,
        )
        _sync_parent(transaction, sync_directory)
    except (DocumentError, OSError) as exc:
        raise recovery_error(
            "atomic export compensation must finish"
        ) from exc


def _sync_parent(
    transaction: ExportTransaction,
    sync_directory: DirectorySync,
) -> None:
    sync_directory(
        transaction.destination.parent,
        transaction.parent_identity,
    )
