"""Idempotent rollback for journaled and compatible legacy exports."""

from __future__ import annotations

from pathlib import Path
from typing import final

from typing_extensions import assert_never

from birkin import store

from .errors import DocumentError, DocumentErrorCode
from .export_destination_lock import destination_lock_path
from .export_io import (
    DirectorySync,
    recovery_error,
)
from .export_paths import valid_staging_paths
from .export_journal import ExportJournal, ExportPhase, ExportTransaction
from .export_types import ExportReceipt, ExportRequest, RollbackReceipt
from .path_security import directory_identity
from .proposal_integrity import authority_digest
from .export_rollback_state import cleanup_backup, require_prior, restore_state


@final
class ExportRollback:
    """Restore exact pre-export state and checkpoint rollback completion."""

    def __init__(
        self,
        backup_root: Path,
        journal: ExportJournal,
        sync_directory: DirectorySync,
    ) -> None:
        self._backup_root = backup_root
        self._journal = journal
        self._sync = sync_directory

    def run(self, receipt: ExportReceipt, destination: Path) -> RollbackReceipt:
        with store.file_lock(
            destination_lock_path(self._backup_root, destination)
        ):
            transaction = self._journal.find_token(receipt.rollback_token)
            if transaction is None:
                raise DocumentError(
                    DocumentErrorCode.PERMISSION_DENIED,
                    "rollback",
                    "durable export transaction is unavailable",
                )
            with store.file_lock(
                self._journal.path_for(transaction.transaction_id),
            ):
                current = self._journal.load(transaction.transaction_id)
                if (
                    current is None
                    or current.rollback_token != receipt.rollback_token
                ):
                    raise DocumentError(
                        DocumentErrorCode.PERMISSION_DENIED,
                        "rollback",
                        "durable export transaction changed",
                    )
                return self._run_locked(current, receipt, destination)

    def _run_locked(
        self,
        transaction: ExportTransaction,
        receipt: ExportReceipt,
        destination: Path,
    ) -> RollbackReceipt:
        self._verify_receipt(transaction, receipt, destination)
        if not transaction.authority_bound:
            transaction = transaction.bind_authority(
                transaction.transaction_id,
                transaction.source_sha256,
            )
            self._journal.write(transaction)
        if directory_identity(destination.parent) != transaction.parent_identity:
            raise DocumentError(
                DocumentErrorCode.PERMISSION_DENIED,
                "rollback",
                "export destination directory identity changed",
            )
        match transaction.phase:
            case ExportPhase.committed:
                transaction = transaction.at(ExportPhase.rolling_back)
                self._journal.write(transaction)
                return self._finish(transaction, receipt)
            case ExportPhase.rolling_back:
                return self._finish(transaction, receipt)
            case ExportPhase.rolled_back:
                require_prior(transaction)
                cleanup_backup(transaction)
                return self._receipt(receipt)
            case ExportPhase.intent | ExportPhase.prepared | ExportPhase.restoring:
                raise recovery_error("export is not committed for rollback", "rollback")
            case unreachable:
                assert_never(unreachable)

    @staticmethod
    def _verify_receipt(
        transaction: ExportTransaction,
        receipt: ExportReceipt,
        destination: Path,
    ) -> None:
        expected_staging = valid_staging_paths(
            destination,
            transaction.transaction_id,
            transaction.rollback_token,
        )
        if (
            not transaction.receipt_authenticated
            or not receipt.receipt_authenticated
            or transaction.rollback_token != receipt.rollback_token
            or transaction.receipt_authenticated
            != receipt.receipt_authenticated
            or transaction.receipt_issued_at != receipt.issued_at
            or transaction.receipt_expires_at != receipt.expires_at
            or transaction.receipt_hmac != receipt.receipt_hmac
            or not ExportRollback._authority_matches(transaction, receipt)
            or transaction.destination != destination
            or transaction.source_sha256 != receipt.source_sha256
            or transaction.output_sha256 != receipt.output_sha256
            or transaction.destination_existed != receipt.destination_existed
            or transaction.destination_sha256 != receipt.destination_sha256
            or transaction.backup != receipt.backup
            or transaction.staging not in expected_staging
        ):
            raise DocumentError(
                DocumentErrorCode.PERMISSION_DENIED,
                "rollback",
                "export transaction and receipt differ",
            )

    @staticmethod
    def _authority_matches(
        transaction: ExportTransaction,
        receipt: ExportReceipt,
    ) -> bool:
        if receipt.authority_bound:
            return (
                transaction.authority_digest == receipt.authority_digest
                and transaction.authority_source_sha256
                == receipt.authority_source_sha256
            )
        candidates = {
            authority_digest(
                receipt.destination,
                receipt.source_sha256,
                ExportRequest(
                    destination=receipt.destination,
                    actor=receipt.actor,
                    proposal_digest=receipt.proposal_digest,
                    operations=receipt.operations,
                    overwrite_approved=overwrite_approved,
                ),
            )
            for overwrite_approved in (False, True)
        }
        return (
            transaction.transaction_id == transaction.authority_digest
            and transaction.authority_digest in candidates
            and transaction.authority_source_sha256 == receipt.source_sha256
        )

    def _finish(
        self, transaction: ExportTransaction, receipt: ExportReceipt
    ) -> RollbackReceipt:
        restore_state(transaction, self._sync)
        self._journal.write(transaction.at(ExportPhase.rolled_back))
        cleanup_backup(transaction)
        return self._receipt(receipt)

    @staticmethod
    def _receipt(receipt: ExportReceipt) -> RollbackReceipt:
        return RollbackReceipt(
            destination=receipt.destination,
            restored=receipt.destination_existed,
            destination_sha256=receipt.destination_sha256,
            actor=receipt.actor,
            proposal_digest=receipt.proposal_digest,
        )
