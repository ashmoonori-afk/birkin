"""Race-safe restoration of an existing export destination."""

from __future__ import annotations

import os
from pathlib import Path

from .errors import DocumentError, DocumentErrorCode
from .export_displacement_restore import restore_displaced
from .export_helper_retire import retire_authenticated_file
from .export_inode_publish import publish_open_file
from .export_io import (
    DirectorySync,
    copy_exact,
    current_hash,
    recovery_error,
    regular_file_identity,
)
from .export_journal_record import ExportTransaction
from .export_no_replace_move import move_no_replace
from .export_open_descriptor import open_export_descriptor
from .path_identity import descriptor_identity
from .path_security import hash_descriptor


def restore_existing(
    transaction: ExportTransaction,
    current: str | None,
    sync_directory: DirectorySync,
) -> None:
    prior = transaction.destination_sha256
    backup = transaction.backup
    if prior is None:
        raise recovery_error("rollback destination proof is incomplete", "rollback")
    checkpoint = transaction.staging.with_name(
        f"{transaction.staging.name}.rollback-replace"
    )
    if current == prior:
        if not _exists(checkpoint):
            return
        published_identity = regular_file_identity(
            transaction.destination,
            "rollback",
        )
        _finish_helpers(
            transaction,
            checkpoint,
            _temporary(transaction),
            prior,
            published_identity,
        )
        sync_directory(
            transaction.destination.parent,
            transaction.parent_identity,
        )
        return
    if backup is None or backup.is_symlink() or not backup.is_file():
        raise _changed("exported destination changed after publication")
    temporary = _prepare_prior(transaction, backup, prior)
    if not _exists(checkpoint):
        if current != transaction.output_sha256:
            raise _changed("exported destination changed after publication")
        try:
            move_no_replace(transaction.destination, checkpoint)
        except FileExistsError as exc:
            raise recovery_error(
                "rollback replacement checkpoint is occupied",
                "rollback",
            ) from exc
    _require_exported_checkpoint(transaction, checkpoint)
    published_identity = _publish_prior(transaction, temporary, prior)
    sync_directory(transaction.destination.parent, transaction.parent_identity)
    _require_prior_destination(transaction, prior, published_identity)
    _finish_helpers(
        transaction,
        checkpoint,
        temporary,
        prior,
        published_identity,
    )
    sync_directory(transaction.destination.parent, transaction.parent_identity)


def _prepare_prior(
    transaction: ExportTransaction,
    backup: Path,
    prior: str,
) -> Path:
    temporary = _temporary(transaction)
    if not _exists(temporary):
        copy_exact(backup, temporary)
    identity = regular_file_identity(temporary, "rollback")
    if (
        current_hash(temporary, "rollback") != prior
        or regular_file_identity(temporary, "rollback") != identity
    ):
        raise recovery_error("rollback staging hash mismatch", "rollback")
    return temporary


def _require_exported_checkpoint(
    transaction: ExportTransaction,
    checkpoint: Path,
) -> None:
    observed = current_hash(checkpoint, "rollback")
    if observed == transaction.output_sha256:
        return
    if observed is not None and current_hash(transaction.destination, "rollback") is None:
        restore_displaced(checkpoint, transaction.destination, observed)
    raise _changed("exported destination changed during rollback displacement")


def _publish_prior(
    transaction: ExportTransaction,
    temporary: Path,
    prior: str,
) -> tuple[int, int]:
    current = current_hash(transaction.destination, "rollback")
    if current == prior:
        return regular_file_identity(transaction.destination, "rollback")
    if current is not None:
        raise recovery_error(
            "rollback destination was concurrently occupied",
            "rollback",
        )
    descriptor = open_export_descriptor(temporary, writable=False)
    try:
        identity = descriptor_identity(descriptor)
        if hash_descriptor(descriptor) != prior:
            raise recovery_error("rollback staging hash mismatch", "rollback")
        try:
            published = publish_open_file(descriptor, transaction.destination)
        except FileExistsError as exc:
            if current_hash(transaction.destination, "rollback") == prior:
                return regular_file_identity(transaction.destination, "rollback")
            raise recovery_error(
                "rollback destination was concurrently occupied",
                "rollback",
            ) from exc
        if descriptor_identity(descriptor) != identity:
            raise recovery_error("rollback staging changed", "rollback")
        return published
    finally:
        os.close(descriptor)


def _require_prior_destination(
    transaction: ExportTransaction,
    prior: str,
    identity: tuple[int, int],
) -> None:
    if (
        regular_file_identity(transaction.destination, "rollback") != identity
        or current_hash(transaction.destination, "rollback") != prior
    ):
        raise recovery_error("rollback replacement must finish", "rollback")


def _finish_helpers(
    transaction: ExportTransaction,
    checkpoint: Path,
    temporary: Path,
    prior: str,
    published_identity: tuple[int, int],
) -> None:
    if not retire_authenticated_file(
        checkpoint,
        transaction.output_sha256,
    ):
        raise recovery_error(
            "rollback replacement checkpoint is unavailable",
            "rollback",
        )
    _ = retire_authenticated_file(
        temporary,
        prior,
        protected_identity=published_identity,
        required=False,
    )


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _temporary(transaction: ExportTransaction) -> Path:
    return transaction.staging.with_name(
        f"{transaction.staging.name}.rollback"
    )


def _changed(message: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.SOURCE_CHANGED,
        "rollback",
        message,
    )
