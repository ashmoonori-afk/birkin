"""Prepared export commit and atomic compensation mechanics."""

from __future__ import annotations

import os
from pathlib import Path

from .artifact_snapshot import SnapshotPath
from .errors import DocumentError, DocumentErrorCode
from .export_io import (
    DirectorySync,
    copy_exact,
    current_hash,
    hash_file,
    regular_file_identity,
    recovery_error,
    reservation_bytes,
    reservation_hash,
)
from .export_journal import ExportJournal, ExportPhase, ExportTransaction
from .journal_record import journal_root
from .path_security import directory_identity


class ExportCommit:
    """Prepare, commit, or compensate one journaled destination replacement."""

    def __init__(
        self,
        backup_root: Path,
        journal: ExportJournal,
        sync_directory: DirectorySync,
    ) -> None:
        self._backup_root = backup_root
        self._journal = journal
        self._sync = sync_directory

    def prepare(self, transaction: ExportTransaction) -> ExportTransaction:
        if transaction.destination_existed:
            backup = transaction.backup
            prior = transaction.destination_sha256
            if backup is None or prior is None:
                raise recovery_error("export backup authority is incomplete")
            root = journal_root(self._backup_root, "export")
            temporary = backup.with_name(f".{backup.name}.prepare")
            if backup.exists() or backup.is_symlink():
                if (
                    backup.is_symlink()
                    or not backup.is_file()
                    or hash_file(backup) != prior
                ):
                    raise recovery_error("export backup no longer matches destination")
            else:
                if current_hash(transaction.destination) != prior:
                    raise DocumentError(
                        DocumentErrorCode.SOURCE_CHANGED,
                        "export",
                        "destination changed before rollback snapshot",
                    )
                if temporary.exists() or temporary.is_symlink():
                    if (
                        temporary.is_symlink()
                        or not temporary.is_file()
                        or hash_file(temporary) != prior
                    ):
                        raise recovery_error("partial export backup is invalid")
                else:
                    copy_exact(transaction.destination, temporary)
                temporary_identity = regular_file_identity(temporary)
                if (
                    hash_file(temporary) != prior
                    or regular_file_identity(temporary) != temporary_identity
                ):
                    raise recovery_error("partial export backup is invalid")
                os.replace(temporary, backup)
                backup_identity = regular_file_identity(backup)
                if (
                    hash_file(backup) != prior
                    or regular_file_identity(backup) != backup_identity
                ):
                    raise recovery_error("export backup no longer matches destination")
            self._sync(root, directory_identity(root))
        elif current_hash(transaction.destination) is not None:
            raise DocumentError(
                DocumentErrorCode.SOURCE_CHANGED,
                "export",
                "new destination appeared before export commit",
            )
        prepared = transaction.at(ExportPhase.prepared)
        self._journal.write(prepared)
        return prepared

    def commit(
        self, transaction: ExportTransaction, source: SnapshotPath
    ) -> ExportTransaction:
        destination = transaction.destination
        current = current_hash(destination)
        if current == transaction.output_sha256:
            self._sync(destination.parent, transaction.parent_identity)
            committed = transaction.at(ExportPhase.committed)
            self._journal.write(committed)
            transaction.staging.unlink(missing_ok=True)
            return committed
        if transaction.destination_existed:
            if current != transaction.destination_sha256:
                raise DocumentError(
                    DocumentErrorCode.SOURCE_CHANGED,
                    "export",
                    "destination changed after its rollback snapshot",
                )
        else:
            self._reserve_new(transaction)
        staging_identity = self._stage(transaction, source)
        if (
            hash_file(transaction.staging) != transaction.output_sha256
            or regular_file_identity(transaction.staging) != staging_identity
        ):
            raise recovery_error("staged export changed before replacement")
        replaced = False
        try:
            os.replace(transaction.staging, destination)
            replaced = True
            self._sync(destination.parent, transaction.parent_identity)
        except (DocumentError, OSError) as failure:
            if not replaced:
                raise recovery_error("export commit failed before replacement") from failure
            restoring = transaction.at(ExportPhase.restoring)
            self._journal.write(restoring)
            try:
                _ = self._restore(restoring, preserve=False)
            except (DocumentError, OSError) as restoration:
                raise recovery_error(
                    "export restoration failed; rollback material was retained"
                ) from restoration
            raise recovery_error(
                "export directory sync failed; original destination was restored"
            ) from failure
        committed = transaction.at(ExportPhase.committed)
        self._journal.write(committed)
        return committed

    def restore(self, transaction: ExportTransaction) -> ExportTransaction:
        """Finish a previously interrupted compensation, preserving retry state."""
        return self._restore(transaction, preserve=True)

    @staticmethod
    def _stage(
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

    @staticmethod
    def _reserve_new(transaction: ExportTransaction) -> None:
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
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            _ = handle.write(marker)
            handle.flush()
            os.fsync(handle.fileno())

    def _restore(
        self, transaction: ExportTransaction, *, preserve: bool
    ) -> ExportTransaction:
        destination = transaction.destination
        current = current_hash(destination)
        if transaction.destination_existed:
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
            if current != prior:
                if current != transaction.output_sha256:
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
                os.replace(temporary, destination)
        elif current is not None:
            if current not in {
                transaction.output_sha256,
                reservation_hash(transaction),
            }:
                raise DocumentError(
                    DocumentErrorCode.SOURCE_CHANGED,
                    "export",
                    "new destination changed during export compensation",
                )
            destination.unlink()
        self._sync(destination.parent, transaction.parent_identity)
        if preserve:
            prepared = transaction.at(ExportPhase.prepared)
            self._journal.write(prepared)
            return prepared
        retired = transaction.at(ExportPhase.rolled_back)
        self._journal.write(retired)
        transaction.staging.unlink(missing_ok=True)
        if transaction.backup is not None:
            transaction.backup.unlink(missing_ok=True)
        return retired
