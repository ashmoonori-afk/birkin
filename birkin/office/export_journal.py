"""Typed write-ahead journal for recoverable caller exports."""

from __future__ import annotations

from pathlib import Path

from .errors import DocumentError, DocumentErrorCode
from .export_journal_record import ExportPhase, ExportTransaction, parse_transaction
from .export_types import ExportRequest
from .journal_record import journal_root, read_record, write_record
from .path_security import directory_identity, sync_directory
from .proposal_integrity import authority_digest

_STAGE = "office_export_journal"
__all__ = ["ExportJournal", "ExportPhase", "ExportTransaction", "transaction_id"]
def transaction_id(
    destination: Path, source_sha256: str, request: ExportRequest
) -> str:
    """Compatibility name for the authority-bound export journal key."""
    return authority_digest(destination, source_sha256, request)


class ExportJournal:
    """One atomic transaction record per exact export authority."""

    def __init__(self, root: Path) -> None:
        self._root = journal_root(root, _STAGE)

    def _path(self, key: str) -> Path:
        if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
            raise DocumentError(
                DocumentErrorCode.PRECONDITION_FAILED,
                _STAGE,
                "export transaction identity is invalid",
            )
        return self._root / f"{key}.json"

    def path_for(self, key: str) -> Path:
        return self._path(key)

    def load(self, key: str) -> ExportTransaction | None:
        record = read_record(self._path(key), _STAGE)
        if record is None:
            return None
        transaction = parse_transaction(record)
        if transaction.transaction_id != key:
            raise DocumentError(
                DocumentErrorCode.PRECONDITION_FAILED,
                _STAGE,
                "export transaction path and identity differ",
            )
        return transaction

    def write(self, transaction: ExportTransaction) -> None:
        write_record(
            self._path(transaction.transaction_id), transaction.record(), _STAGE
        )

    def remove(self, transaction: ExportTransaction) -> None:
        path = self._path(transaction.transaction_id)
        try:
            path.unlink(missing_ok=True)
            sync_directory(self._root, directory_identity(self._root))
        except OSError as exc:
            raise DocumentError(
                DocumentErrorCode.PRECONDITION_FAILED,
                _STAGE,
                "export transaction cleanup failed",
                retryable=True,
            ) from exc

    def find_token(self, token: str) -> ExportTransaction | None:
        found: ExportTransaction | None = None
        for path in self._root.glob("*.json"):
            record = read_record(path, _STAGE)
            if record is None:
                continue
            transaction = parse_transaction(record)
            if path.stem != transaction.transaction_id:
                raise DocumentError(
                    DocumentErrorCode.PRECONDITION_FAILED,
                    _STAGE,
                    "export transaction path and identity differ",
                )
            if transaction.rollback_token == token:
                if found is not None:
                    raise DocumentError(
                        DocumentErrorCode.PRECONDITION_FAILED,
                        _STAGE,
                        "rollback token identifies multiple export transactions",
                    )
                found = transaction
        return found
