"""Lossless write-ahead orchestration for caller exports."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import final

from typing_extensions import assert_never

from .artifact_snapshot import SnapshotPath
from .errors import DocumentError, DocumentErrorCode
from .export_commit import ExportCommit
from .export_io import DirectorySync, current_hash, hash_file, recovery_error
from .export_journal import (
    ExportJournal,
    ExportPhase,
    ExportTransaction,
    transaction_id,
)
from .export_rollback import ExportRollback
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
        transaction = self._journal.load(key)
        if transaction is None:
            transaction = self._begin(destination, source_sha256, request)
        elif transaction.phase is ExportPhase.rolled_back:
            self._retire(transaction)
            transaction = self._begin(destination, source_sha256, request)
        self._verify_identity(transaction, destination, source_sha256)
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
                return self._receipt(transaction, request)
            case ExportPhase.rolling_back:
                raise recovery_error("export rollback must finish before publication")
            case ExportPhase.rolled_back:
                raise recovery_error("rolled-back export transaction was not renewed")
            case unreachable:
                assert_never(unreachable)
        return self._receipt(commit.commit(transaction, source), request)

    def rollback(
        self, receipt: ExportReceipt, destination: Path
    ) -> RollbackReceipt:
        return ExportRollback(self._journal, self._sync).run(receipt, destination)

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
        token = uuid.uuid4().hex
        transaction = ExportTransaction(
            transaction_id=key,
            phase=ExportPhase.intent,
            rollback_token=token,
            destination=destination,
            source_sha256=source_sha256,
            output_sha256=source_sha256,
            destination_existed=existed,
            destination_sha256=hash_file(destination) if existed else None,
            backup=self._backup_root / f"{token}.bak" if existed else None,
            staging=destination.parent / f".birkin-export-{key}{destination.suffix}",
            parent_identity=directory_identity(destination.parent),
        )
        self._journal.write(transaction)
        return transaction

    def _verify_identity(
        self,
        transaction: ExportTransaction,
        destination: Path,
        source_sha256: str,
    ) -> None:
        if (
            transaction.destination != destination
            or transaction.source_sha256 != source_sha256
            or transaction.output_sha256 != source_sha256
            or transaction.staging.parent != destination.parent
            or directory_identity(destination.parent) != transaction.parent_identity
            or (
                transaction.backup is not None
                and transaction.backup.parent != self._backup_root
            )
        ):
            raise DocumentError(
                DocumentErrorCode.POLICY_DENIED,
                "export",
                "export transaction does not match approved authority",
            )

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
        transaction.staging.unlink(missing_ok=True)
        if transaction.backup is not None:
            transaction.backup.unlink(missing_ok=True)

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
            or not transaction.backup.is_file()
            or hash_file(transaction.backup) != transaction.destination_sha256
        ):
            raise recovery_error("committed export rollback material is unavailable")

    @staticmethod
    def _receipt(
        transaction: ExportTransaction, request: ExportRequest
    ) -> ExportReceipt:
        return ExportReceipt(
            rollback_token=transaction.rollback_token,
            destination=transaction.destination,
            source_sha256=transaction.source_sha256,
            output_sha256=transaction.output_sha256,
            operations=tuple(dict(operation) for operation in request.operations),
            actor=request.actor,
            proposal_digest=request.proposal_digest,
            destination_existed=transaction.destination_existed,
            destination_sha256=transaction.destination_sha256,
            backup=transaction.backup,
        )
