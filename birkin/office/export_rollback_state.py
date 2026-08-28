"""Identity-checked filesystem state restoration for export rollback."""

from __future__ import annotations

import os
from pathlib import Path

from .errors import DocumentError, DocumentErrorCode
from .export_io import (
    DirectorySync,
    copy_exact,
    current_hash as _current_hash,
    hash_file as _hash_file,
    recovery_error,
    regular_file_identity,
)
from .export_journal_record import ExportTransaction
from .export_displacement_restore import restore_displaced
from .export_helper_retire import retire_authenticated_file
from .export_no_replace_move import move_no_replace
from .retention_backup_cleanup import remove_authenticated_backup


def destination_hash(path: Path, stage: str = "rollback") -> str | None:
    return _current_hash(path, stage)


def state_file_hash(path: Path) -> str:
    return _hash_file(path)


def cleanup_backup(transaction: ExportTransaction) -> None:
    backup = transaction.backup
    prior = transaction.destination_sha256
    if backup is None:
        return
    if prior is None:
        raise recovery_error(
            "rollback backup authority is incomplete",
            "rollback",
        )
    _ = remove_authenticated_backup(backup, prior)


def restore_state(
    transaction: ExportTransaction,
    sync_directory: DirectorySync,
) -> None:
    try:
        _restore_state(transaction, sync_directory)
    except DocumentError:
        raise
    except OSError as exc:
        raise recovery_error(
            "rollback filesystem recovery must finish",
            "rollback",
        ) from exc


def _restore_state(
    transaction: ExportTransaction,
    sync_directory: DirectorySync,
) -> None:
    current = destination_hash(transaction.destination)
    delete_checkpoint = transaction.staging.with_name(
        f"{transaction.staging.name}.rollback-delete"
    )
    if (
        not transaction.destination_existed
        and current is None
        and (delete_checkpoint.exists() or delete_checkpoint.is_symlink())
    ):
        _finish_delete_checkpoint(transaction, delete_checkpoint)
    if transaction.destination_existed:
        _restore_existing(transaction, current)
    elif current is not None:
        _remove_new(transaction, current, delete_checkpoint)
    sync_directory(transaction.destination.parent, transaction.parent_identity)


def require_prior(transaction: ExportTransaction) -> None:
    current = destination_hash(transaction.destination)
    expected = (
        transaction.destination_sha256 if transaction.destination_existed else None
    )
    if current != expected:
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "rollback",
            "rolled-back destination state changed",
        )


def _finish_delete_checkpoint(
    transaction: ExportTransaction,
    checkpoint: Path,
) -> None:
    try:
        retired = retire_authenticated_file(
            checkpoint,
            transaction.output_sha256,
        )
    except DocumentError as exc:
        raise recovery_error(
            "rollback deletion checkpoint changed",
            "rollback",
        ) from exc
    if not retired:
        raise recovery_error(
            "rollback deletion checkpoint is unavailable",
            "rollback",
        )


def _restore_existing(
    transaction: ExportTransaction,
    current: str | None,
) -> None:
    prior = transaction.destination_sha256
    backup = transaction.backup
    if prior is None:
        raise recovery_error("rollback destination proof is incomplete", "rollback")
    if current == prior:
        return
    if (
        current != transaction.output_sha256
        or backup is None
        or backup.is_symlink()
        or not backup.is_file()
    ):
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "rollback",
            "exported destination changed after publication",
        )
    temporary = transaction.staging.with_name(
        f"{transaction.staging.name}.rollback"
    )
    if not temporary.exists() and not temporary.is_symlink():
        copy_exact(backup, temporary)
    temporary_identity = regular_file_identity(temporary, "rollback")
    if (
        state_file_hash(temporary) != prior
        or regular_file_identity(temporary, "rollback") != temporary_identity
    ):
        raise recovery_error("rollback staging hash mismatch", "rollback")
    if (
        destination_hash(transaction.destination)
        != transaction.output_sha256
    ):
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "rollback",
            "exported destination changed during rollback",
        )
    os.replace(temporary, transaction.destination)
    if destination_hash(transaction.destination) != prior:
        raise recovery_error("rollback replacement must finish", "rollback")


def _remove_new(
    transaction: ExportTransaction,
    current: str,
    checkpoint: Path,
) -> None:
    if current != transaction.output_sha256:
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "rollback",
            "exported destination changed after publication",
        )
    try:
        move_no_replace(transaction.destination, checkpoint)
    except FileExistsError as exc:
        raise recovery_error(
            "rollback deletion checkpoint is occupied",
            "rollback",
        ) from exc
    checkpoint_sha256 = state_file_hash(checkpoint)
    if checkpoint_sha256 != transaction.output_sha256:
        restore_displaced(
            checkpoint,
            transaction.destination,
            checkpoint_sha256,
        )
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "rollback",
            "exported destination changed during deletion",
        )
    _finish_delete_checkpoint(transaction, checkpoint)
    if destination_hash(transaction.destination) is not None:
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "rollback",
            "rollback destination was concurrently recreated",
        )
