"""Idempotent rollback for journaled and compatible legacy exports."""

from __future__ import annotations

import os
from pathlib import Path
from typing import final

from typing_extensions import assert_never

from .errors import DocumentError, DocumentErrorCode
from .export_io import (
    DirectorySync,
    copy_exact,
    current_hash,
    hash_file,
    recovery_error,
    regular_file_identity,
)
from .export_journal import ExportJournal, ExportPhase, ExportTransaction
from .export_types import ExportReceipt, ExportRequest, RollbackReceipt
from .path_security import directory_identity
from .proposal_integrity import authority_digest


@final
class ExportRollback:
    """Restore exact pre-export state and checkpoint rollback completion."""

    def __init__(self, journal: ExportJournal, sync_directory: DirectorySync) -> None:
        self._journal = journal
        self._sync = sync_directory

    def run(self, receipt: ExportReceipt, destination: Path) -> RollbackReceipt:
        transaction = self._journal.find_token(receipt.rollback_token)
        if transaction is None:
            raise DocumentError(
                DocumentErrorCode.PERMISSION_DENIED,
                "rollback",
                "durable export transaction is unavailable",
            )
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
                self._require_prior(transaction)
                if transaction.backup is not None:
                    transaction.backup.unlink(missing_ok=True)
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
        expected_staging = (
            destination.parent
            / f".birkin-export-{transaction.transaction_id}{destination.suffix}"
        )
        if (
            transaction.rollback_token != receipt.rollback_token
            or not ExportRollback._authority_matches(transaction, receipt)
            or transaction.destination != destination
            or transaction.source_sha256 != receipt.source_sha256
            or transaction.output_sha256 != receipt.output_sha256
            or transaction.destination_existed != receipt.destination_existed
            or transaction.destination_sha256 != receipt.destination_sha256
            or transaction.backup != receipt.backup
            or transaction.staging != expected_staging
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
        self._restore_state(transaction)
        self._journal.write(transaction.at(ExportPhase.rolled_back))
        if transaction.backup is not None:
            transaction.backup.unlink(missing_ok=True)
        return self._receipt(receipt)

    def _restore_state(self, transaction: ExportTransaction) -> None:
        current = current_hash(transaction.destination, "rollback")
        if transaction.destination_existed:
            prior = transaction.destination_sha256
            backup = transaction.backup
            if prior is None:
                raise recovery_error("rollback destination proof is incomplete", "rollback")
            if current != prior:
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
                    hash_file(temporary) != prior
                    or regular_file_identity(temporary, "rollback")
                    != temporary_identity
                ):
                    raise recovery_error("rollback staging hash mismatch", "rollback")
                os.replace(temporary, transaction.destination)
        elif current is not None:
            if current != transaction.output_sha256:
                raise DocumentError(
                    DocumentErrorCode.SOURCE_CHANGED,
                    "rollback",
                    "exported destination changed after publication",
                )
            transaction.destination.unlink()
        self._sync(transaction.destination.parent, transaction.parent_identity)

    @staticmethod
    def _require_prior(transaction: ExportTransaction) -> None:
        current = current_hash(transaction.destination, "rollback")
        expected = (
            transaction.destination_sha256 if transaction.destination_existed else None
        )
        if current != expected:
            raise DocumentError(
                DocumentErrorCode.SOURCE_CHANGED,
                "rollback",
                "rolled-back destination state changed",
            )

    @staticmethod
    def _receipt(receipt: ExportReceipt) -> RollbackReceipt:
        return RollbackReceipt(
            destination=receipt.destination,
            restored=receipt.destination_existed,
            destination_sha256=receipt.destination_sha256,
            actor=receipt.actor,
            proposal_digest=receipt.proposal_digest,
        )
