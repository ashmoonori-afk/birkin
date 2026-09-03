"""Lossless write-ahead orchestration for caller exports."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import final

from typing_extensions import assert_never

from .artifact_snapshot import SnapshotPath
from .errors import DocumentError, DocumentErrorCode
from .export_commit import ExportCommit
from .export_destination_lock import export_transaction_lock
from .export_io import DirectorySync, current_hash, hash_file, recovery_error
from .export_helper_retire import retire_authenticated_file
from .export_journal import (
    ExportJournal,
    ExportPhase,
    ExportTransaction,
    transaction_id,
)
from .export_rollback import ExportRollback
from .export_paths import staging_path, valid_staging_paths
from .export_transaction_receipt import (
    approved_export_authority,
    seal_transaction_receipt,
    transaction_receipt,
)
from .export_types import ExportReceipt, ExportRequest, RollbackReceipt
from .path_security import directory_identity


@final
class ExportTransactionRunner:
    """Execute one exact caller export as a recoverable filesystem transaction."""

    def __init__(self, backup_root: Path, sync_directory: DirectorySync) -> None:
        self._backup_root = backup_root
        self._journal = ExportJournal(backup_root.parent / "export-journal")
        self._sync = sync_directory

    def export(
        self, source: SnapshotPath, destination: Path, request: ExportRequest
    ) -> ExportReceipt:
        source_sha256 = source.sha256()
        key = transaction_id(destination, source_sha256, request)
        with export_transaction_lock(self._backup_root, destination, self._journal, key):
            return self._export_locked(
                source, destination, request, source_sha256, key
            )

    def _export_locked(
        self,
        source: SnapshotPath,
        destination: Path,
        request: ExportRequest,
        source_sha256: str,
        key: str,
    ) -> ExportReceipt:
        transaction = self._journal.load(key)
        if transaction is None:
            transaction = self._begin(destination, source_sha256, request)
        else:
            transaction = self._verify_identity(
                transaction,
                destination,
                source_sha256,
                request,
            )
            if transaction.phase is ExportPhase.rolled_back:
                self._retire(transaction)
                transaction = self._begin(destination, source_sha256, request)
        sealed = seal_transaction_receipt(
            transaction,
            request,
            self._backup_root.parents[1],
            enforce_retention=transaction.phase is ExportPhase.committed,
        )
        if sealed != transaction:
            self._journal.write(sealed)
        transaction = sealed
        commit = ExportCommit(self._backup_root, self._journal, self._sync)
        match transaction.phase:
            case ExportPhase.intent:
                transaction = commit.prepare(transaction)
            case ExportPhase.prepared:
                pass
            case ExportPhase.restoring:
                transaction = commit.restore(transaction)
            case ExportPhase.committed:
                self._require_output(transaction)
                return transaction_receipt(transaction, request)
            case ExportPhase.rolling_back:
                raise recovery_error("export rollback must finish before publication")
            case ExportPhase.rolled_back:
                raise recovery_error("rolled-back export transaction was not renewed")
            case unreachable:
                assert_never(unreachable)
        return transaction_receipt(commit.commit(transaction, source), request)

    def rollback(
        self, receipt: ExportReceipt, destination: Path
    ) -> RollbackReceipt:
        return ExportRollback(
            self._backup_root,
            self._journal,
            self._sync,
        ).run(receipt, destination)

    def _begin(
        self,
        destination: Path,
        source_sha256: str,
        request: ExportRequest,
    ) -> ExportTransaction:
        existed = destination.exists() or destination.is_symlink()
        if existed and not request.overwrite_approved:
            raise DocumentError(
                DocumentErrorCode.OUTPUT_EXISTS,
                "export",
                "destination exists and overwrite approval is absent",
                details={"reason": "overwrite_approval_required"},
            )
        if existed and (destination.is_symlink() or not destination.is_file()):
            raise DocumentError(
                DocumentErrorCode.PERMISSION_DENIED,
                "export",
                "export destination must be a regular file",
            )
        key = transaction_id(destination, source_sha256, request)
        digest, authority_source_sha256 = approved_export_authority(
            destination,
            source_sha256,
            request,
        )
        token = uuid.uuid4().hex
        transaction = ExportTransaction(
            transaction_id=key,
            authority_digest=digest,
            authority_source_sha256=authority_source_sha256,
            authority_bound=True,
            receipt_authenticated=True,
            receipt_issued_at=None,
            receipt_expires_at=None,
            receipt_hmac=None,
            phase=ExportPhase.intent,
            rollback_token=token,
            destination=destination,
            source_sha256=source_sha256,
            output_sha256=source_sha256,
            destination_existed=existed,
            destination_sha256=hash_file(destination) if existed else None,
            backup=self._backup_root / f"{token}.bak" if existed else None,
            staging=staging_path(destination, key, token),
            parent_identity=directory_identity(destination.parent),
        )
        transaction = seal_transaction_receipt(
            transaction,
            request,
            self._backup_root.parents[1],
        )
        self._journal.write(transaction)
        return transaction

    def _verify_identity(
        self,
        transaction: ExportTransaction,
        destination: Path,
        source_sha256: str,
        request: ExportRequest,
    ) -> ExportTransaction:
        expected_authority_digest, authority_source_sha256 = (
            approved_export_authority(
                destination,
                source_sha256,
                request,
            )
        )
        expected_staging = valid_staging_paths(
            destination,
            transaction.transaction_id,
            transaction.rollback_token,
        )
        expected_backup = (
            self._backup_root / f"{transaction.rollback_token}.bak"
            if transaction.destination_existed
            else None
        )
        if (
            transaction.destination != destination
            or transaction.source_sha256 != source_sha256
            or transaction.output_sha256 != source_sha256
            or transaction.transaction_id
            != transaction_id(destination, source_sha256, request)
            or transaction.staging not in expected_staging
            or transaction.backup != expected_backup
            or directory_identity(destination.parent) != transaction.parent_identity
            or (
                transaction.authority_bound
                and (
                    transaction.authority_digest != expected_authority_digest
                    or transaction.authority_source_sha256
                    != authority_source_sha256
                )
            )
        ):
            raise DocumentError(
                DocumentErrorCode.POLICY_DENIED,
                "export",
                "export transaction does not match approved authority",
            )
        if transaction.authority_bound:
            return transaction
        upgraded = transaction.bind_authority(
            expected_authority_digest,
            authority_source_sha256,
        )
        self._journal.write(upgraded)
        return upgraded

    @staticmethod
    def _retire(transaction: ExportTransaction) -> None:
        expected = (
            transaction.destination_sha256
            if transaction.destination_existed
            else None
        )
        if current_hash(transaction.destination) != expected:
            raise DocumentError(
                DocumentErrorCode.SOURCE_CHANGED,
                "export",
                "compensated export destination changed",
            )
        _ = retire_authenticated_file(
            transaction.staging,
            transaction.output_sha256,
            required=False,
        )
        if transaction.backup is not None:
            prior = transaction.destination_sha256
            if prior is not None:
                _ = retire_authenticated_file(
                    transaction.backup,
                    prior,
                    required=False,
                )

    @staticmethod
    def _require_output(transaction: ExportTransaction) -> None:
        if current_hash(transaction.destination) != transaction.output_sha256:
            raise DocumentError(
                DocumentErrorCode.SOURCE_CHANGED,
                "export",
                "committed export destination changed",
            )
        if transaction.destination_existed and (
            transaction.backup is None
            or transaction.backup.is_symlink()
            or not transaction.backup.is_file()
            or hash_file(transaction.backup) != transaction.destination_sha256
        ):
            raise recovery_error("committed export rollback material is unavailable")
