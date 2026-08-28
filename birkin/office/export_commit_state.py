"""Prepared export staging, reservation, and compensation state."""

from __future__ import annotations

import os

from .artifact_snapshot import SnapshotPath
from .errors import DocumentError, DocumentErrorCode
from .export_atomic_publish import has_valid_displacement
from .export_io import (
    DirectorySync,
    copy_exact,
    current_hash,
    hash_file,
    recovery_error,
    regular_file_identity,
    reservation_bytes,
    reservation_hash,
)
from .export_journal import ExportJournal, ExportPhase, ExportTransaction


def require_destination_state(transaction: ExportTransaction) -> None:
    expected = (
        transaction.destination_sha256
        if transaction.destination_existed
        else reservation_hash(transaction)
    )
    if (
        current_hash(transaction.destination) != expected
        and not has_valid_displacement(transaction)
    ):
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "export",
            "destination changed before atomic replacement",
        )


def stage_export(
    transaction: ExportTransaction,
    source: SnapshotPath,
) -> tuple[int, int]:
    staging = transaction.staging
    if staging.exists() or staging.is_symlink():
        staging_identity = regular_file_identity(staging)
        if (
            hash_file(staging) != transaction.output_sha256
            or regular_file_identity(staging) != staging_identity
        ):
            raise recovery_error("staged export does not match validated draft")
        return staging_identity
    copy_exact(source, staging)
    staging_identity = regular_file_identity(staging)
    staged_sha256 = hash_file(staging)
    if (
        staged_sha256 != transaction.output_sha256
        or regular_file_identity(staging) != staging_identity
    ):
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "export",
            "export copy does not match the validated draft",
            artifact_sha256=staged_sha256,
        )
    return staging_identity


def reserve_new(transaction: ExportTransaction) -> None:
    destination = transaction.destination
    marker = reservation_bytes(transaction)
    if destination.exists() or destination.is_symlink():
        if (
            destination.is_symlink()
            or not destination.is_file()
            or destination.read_bytes() != marker
        ):
            raise DocumentError(
                DocumentErrorCode.SOURCE_CHANGED,
                "export",
                "new destination was occupied during export",
            )
        return
    descriptor = os.open(
        destination,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    with os.fdopen(descriptor, "wb") as handle:
        _ = handle.write(marker)
        handle.flush()
        os.fsync(handle.fileno())


def restore_export(
    transaction: ExportTransaction,
    *,
    preserve: bool,
    force: bool,
    journal: ExportJournal,
    sync_directory: DirectorySync,
) -> ExportTransaction:
    destination = transaction.destination
    forced = force or transaction.phase is ExportPhase.restoring
    try:
        current = current_hash(destination)
    except DocumentError:
        if not forced:
            raise
        current = None
    if transaction.destination_existed:
        _restore_existing(transaction, current, forced)
    elif current is not None or (
        forced and (destination.exists() or destination.is_symlink())
    ):
        if current not in {
            transaction.output_sha256,
            reservation_hash(transaction),
        } and not forced:
            raise DocumentError(
                DocumentErrorCode.SOURCE_CHANGED,
                "export",
                "new destination changed during export compensation",
            )
        destination.unlink()
    sync_directory(destination.parent, transaction.parent_identity)
    if preserve:
        prepared = transaction.at(ExportPhase.prepared)
        journal.write(prepared)
        return prepared
    retired = transaction.at(ExportPhase.rolled_back)
    journal.write(retired)
    transaction.staging.unlink(missing_ok=True)
    if transaction.backup is not None:
        transaction.backup.unlink(missing_ok=True)
    return retired


def _restore_existing(
    transaction: ExportTransaction,
    current: str | None,
    forced: bool,
) -> None:
    backup = transaction.backup
    prior = transaction.destination_sha256
    if (
        backup is None
        or prior is None
        or backup.is_symlink()
        or not backup.is_file()
        or hash_file(backup) != prior
    ):
        raise recovery_error("rollback backup is unavailable or changed")
    if current == prior:
        return
    if current != transaction.output_sha256 and not forced:
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "export",
            "destination changed during export compensation",
        )
    temporary = transaction.staging.with_name(
        f"{transaction.staging.name}.restore"
    )
    if not temporary.exists() and not temporary.is_symlink():
        copy_exact(backup, temporary)
    temporary_identity = regular_file_identity(temporary)
    if (
        hash_file(temporary) != prior
        or regular_file_identity(temporary) != temporary_identity
    ):
        raise recovery_error("staged export restoration is invalid")
    os.replace(temporary, transaction.destination)
