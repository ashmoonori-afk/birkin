"""Bounded retention and purge for terminal Office export authority."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TypeGuard, cast

from birkin import store

from .errors import DocumentError, DocumentErrorCode
from .export_journal import ExportJournal
from .export_journal_record import ExportTransaction
from .job_journal import OfficeJobJournal
from .path_security import directory_identity, sync_directory
from .receipt_auth import RETENTION_DAYS, verified_receipt_window
from .retention_backup_cleanup import receipt_backup_hash, remove_authenticated_backup

_TERMINAL_STATES = frozenset({"exported", "rejected", "failed"})
_STAGE = "office_retention"


def purge_expired_office_state(
    office_home: Path,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    counts = {"jobs": 0, "backups": 0, "transactions": 0}
    jobs = office_home / "jobs"
    if jobs.is_symlink():
        raise _error("job journal root is invalid")
    if not jobs.is_dir():
        return counts
    job_journal = OfficeJobJournal(jobs)
    backup_root = office_home / "artifacts" / "export-backups"
    if backup_root.is_symlink() or (
        backup_root.exists() and not backup_root.is_dir()
    ):
        raise _error("export backup root is invalid")
    journal = ExportJournal(office_home / "artifacts" / "export-journal")
    for job_id in job_journal.list_all():
        path = job_journal.path_for(job_id)
        try:
            with store.file_lock(path, timeout=0):
                record = job_journal.latest(job_id)
                rolled_back = (
                    record.get("state") == "validated"
                    and _is_mapping(record.get("rollback"))
                )
                if (
                    record.get("state") not in _TERMINAL_STATES
                    and not rolled_back
                ):
                    continue
                removed = _purge_job(
                    office_home,
                    backup_root,
                    journal,
                    job_journal,
                    job_id,
                    path,
                    current,
                )
        except store.FileLockTimeout:
            continue
        except DocumentError:
            if not path.exists() and not path.is_symlink():
                continue
            raise
        for key, amount in removed.items():
            counts[key] += amount
    return counts


def _purge_job(
    office_home: Path,
    backup_root: Path,
    journal: ExportJournal,
    job_journal: OfficeJobJournal,
    job_id: str,
    path: Path,
    current: datetime,
) -> dict[str, int]:
    removed = {"jobs": 0, "backups": 0, "transactions": 0}
    record = job_journal.latest(job_id)
    if record.get("job_id") != job_id:
        raise _error("job receipt path and identity differ")
    export = record.get("export")
    rolled_back = (
        record.get("state") == "validated"
        and _is_mapping(record.get("rollback"))
    )
    if (
        record.get("state") == "exported" or rolled_back
    ) and not _is_mapping(export):
        raise _error("terminal export receipt is unavailable")
    if _is_mapping(export):
        token = export.get("rollback_token")
        if not isinstance(token, str):
            raise _error("export receipt rollback token is invalid")
        transaction = journal.find_token(token)
        expires = _expiry(
            office_home,
            path,
            export,
            transaction,
        )
        if current < expires:
            return removed
        if transaction is None:
            if export.get("receipt_hmac") is not None:
                removed["backups"] += _cleanup_signed_backup(
                    backup_root,
                    token,
                    export,
                )
            job_journal.remove(job_id)
            removed["jobs"] += 1
            return removed
        with store.file_lock(journal.path_for(transaction.transaction_id), timeout=0):
            transaction = journal.load(transaction.transaction_id)
            if transaction is None:
                if export.get("receipt_hmac") is not None:
                    removed["backups"] += _cleanup_signed_backup(
                        backup_root,
                        token,
                        export,
                    )
                job_journal.remove(job_id)
                removed["jobs"] += 1
                return removed
            if transaction.rollback_token != token:
                raise _error(
                    "export transaction changed during purge",
                    retryable=True,
                )
            _ = _expiry(office_home, path, export, transaction)
            expected_backup = (
                backup_root / f"{token}.bak"
                if transaction.destination_existed
                else None
            )
            if transaction.backup != expected_backup:
                raise _error("export backup path is invalid")
            if expected_backup is not None:
                removed["backups"] += _cleanup_backup(
                    backup_root,
                    expected_backup,
                    transaction.destination_sha256,
                )
            journal.remove(transaction)
            removed["transactions"] += 1
    else:
        expires = _legacy_expiry(path)
        if current < expires:
            return removed
    job_journal.remove(job_id)
    removed["jobs"] += 1
    return removed


def _cleanup_signed_backup(
    backup_root: Path,
    token: str,
    export: Mapping[str, object],
) -> int:
    existed = export.get("destination_existed")
    if not isinstance(existed, bool):
        raise _error("export receipt destination state is invalid")
    if not existed:
        return 0
    return _cleanup_backup(
        backup_root,
        backup_root / f"{token}.bak",
        receipt_backup_hash(export),
    )


def _cleanup_backup(
    backup_root: Path,
    backup: Path,
    expected_sha256: str | None,
) -> int:
    if expected_sha256 is None:
        raise _error("export backup hash is invalid")
    try:
        removed = remove_authenticated_backup(
            backup,
            expected_sha256,
        )
        if removed:
            sync_directory(
                backup_root,
                directory_identity(backup_root),
            )
        return removed
    except (DocumentError, OSError) as exc:
        raise _error(
            "export backup cleanup must finish",
            retryable=True,
        ) from exc
def _expiry(
    office_home: Path,
    path: Path,
    export: Mapping[str, object],
    transaction: ExportTransaction | None,
) -> datetime:
    if transaction is None:
        if export.get("receipt_hmac") is None:
            return _legacy_expiry(path)
        _, expires = verified_receipt_window(export, office_home)
        return expires
    if not transaction.receipt_authenticated:
        if export.get("receipt_hmac") is not None:
            raise _error("legacy export receipt provenance is invalid")
        return _legacy_expiry(path)
    if not _signed_receipt_matches(transaction, export):
        raise _error("export receipt and transaction differ")
    _, expires = verified_receipt_window(export, office_home)
    return expires


def _legacy_expiry(path: Path) -> datetime:
    return datetime.fromtimestamp(
        path.stat().st_mtime,
        timezone.utc,
    ) + timedelta(days=RETENTION_DAYS)


def _signed_receipt_matches(
    transaction: ExportTransaction,
    receipt: Mapping[str, object],
) -> bool:
    return (
        receipt.get("rollback_token") == transaction.rollback_token
        and receipt.get("path") == str(transaction.destination)
        and receipt.get("authority_digest") == transaction.authority_digest
        and receipt.get("authority_source_sha256")
        == transaction.authority_source_sha256
        and receipt.get("source_sha256") == transaction.source_sha256
        and receipt.get("output_sha256") == transaction.output_sha256
        and receipt.get("destination_existed")
        == transaction.destination_existed
        and receipt.get("destination_sha256")
        == transaction.destination_sha256
        and receipt.get("issued_at") == transaction.receipt_issued_at
        and receipt.get("expires_at") == transaction.receipt_expires_at
        and receipt.get("receipt_hmac") == transaction.receipt_hmac
    )


def _is_mapping(
    value: object,
) -> TypeGuard[Mapping[str, object]]:
    if not isinstance(value, Mapping):
        return False
    mapping = cast("Mapping[object, object]", value)
    return all(isinstance(key, str) for key in mapping)


def _error(message: str, *, retryable: bool = False) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.PRECONDITION_FAILED,
        _STAGE,
        message,
        retryable=retryable,
    )
