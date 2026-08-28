"""Prepared export commit and atomic compensation mechanics."""

from __future__ import annotations

import os
from pathlib import Path
from typing import final

from .artifact_snapshot import SnapshotPath
from .errors import DocumentError, DocumentErrorCode
from .export_atomic_publish import (
    finish_published_checkpoint,
    has_valid_displacement,
    publish_staged,
)
from .export_commit_state import (
    require_destination_state,
    reserve_new,
    restore_export,
    stage_export,
)
from .export_io import (
    DirectorySync,
    copy_exact,
    current_hash,
    hash_file,
    regular_file_identity,
    recovery_error,
)
from .export_helper_retire import retire_authenticated_file
from .export_journal import ExportJournal, ExportPhase, ExportTransaction
from .journal_record import journal_root
from .path_security import (
    close_guard,
    directory_identity,
    open_identity_guard,
)


@final
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
            finish_published_checkpoint(transaction, self._sync)
            self._sync(destination.parent, transaction.parent_identity)
            committed = transaction.at(ExportPhase.committed)
            self._journal.write(committed)
            _ = retire_authenticated_file(
                transaction.staging,
                transaction.output_sha256,
                protected_identity=regular_file_identity(destination),
                required=False,
            )
            return committed
        checkpointed = has_valid_displacement(transaction)
        if transaction.destination_existed:
            if current != transaction.destination_sha256 and not checkpointed:
                raise DocumentError(
                    DocumentErrorCode.SOURCE_CHANGED,
                    "export",
                    "destination changed after its rollback snapshot",
                )
        elif not checkpointed:
            self._reserve_new(transaction)
        staging_identity = self.stage(transaction, source)
        if (
            hash_file(transaction.staging) != transaction.output_sha256
            or regular_file_identity(transaction.staging) != staging_identity
        ):
            raise recovery_error("staged export changed before replacement")
        staging_guard = (
            open_identity_guard(transaction.staging, staging_identity)
            if os.name != "nt"
            else -1
        )
        try:
            self.require_destination_state(transaction)
            publish_staged(transaction, staging_identity, self._sync)
        finally:
            if staging_guard >= 0:
                close_guard(staging_guard)
        committed = transaction.at(ExportPhase.committed)
        self._journal.write(committed)
        return committed

    @staticmethod
    def require_destination_state(
        transaction: ExportTransaction,
    ) -> None:
        require_destination_state(transaction)

    def restore(self, transaction: ExportTransaction) -> ExportTransaction:
        """Finish a previously interrupted compensation, preserving retry state."""
        return restore_export(
            transaction,
            preserve=True,
            force=False,
            journal=self._journal,
            sync_directory=self._sync,
        )

    @staticmethod
    def stage(
        transaction: ExportTransaction,
        source: SnapshotPath,
    ) -> tuple[int, int]:
        return stage_export(transaction, source)

    @staticmethod
    def _reserve_new(transaction: ExportTransaction) -> None:
        reserve_new(transaction)
