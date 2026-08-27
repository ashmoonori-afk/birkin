"""Typed write-ahead journal for recoverable caller exports."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from .errors import DocumentError, DocumentErrorCode
from .export_types import ExportRequest
from .journal_record import journal_root, read_record, write_record
from .proposal_integrity import authority_digest

_STAGE = "office_export_journal"
_VERSION = 2
_FIELDS_V1 = frozenset(
    {
        "version", "transaction_id", "phase", "rollback_token", "destination",
        "source_sha256", "output_sha256", "destination_existed",
        "destination_sha256", "backup", "staging", "parent_identity",
    }
)
_FIELDS = _FIELDS_V1 | {
    "authority_digest",
    "authority_source_sha256",
}


class ExportPhase(str, Enum):
    intent = "intent"
    prepared = "prepared"
    restoring = "restoring"
    committed = "committed"
    rolling_back = "rolling_back"
    rolled_back = "rolled_back"


@dataclass(frozen=True, slots=True)
class ExportTransaction:
    transaction_id: str
    authority_digest: str
    authority_source_sha256: str
    authority_bound: bool
    phase: ExportPhase
    rollback_token: str
    destination: Path
    source_sha256: str
    output_sha256: str
    destination_existed: bool
    destination_sha256: str | None
    backup: Path | None
    staging: Path
    parent_identity: tuple[int, int]

    def at(self, phase: ExportPhase) -> ExportTransaction:
        return replace(self, phase=phase)

    def bind_authority(
        self,
        digest: str,
        source_sha256: str,
    ) -> ExportTransaction:
        return replace(
            self,
            authority_digest=digest,
            authority_source_sha256=source_sha256,
            authority_bound=True,
        )

    def record(self) -> dict[str, object]:
        return {
            "version": _VERSION,
            "transaction_id": self.transaction_id,
            "authority_digest": self.authority_digest,
            "authority_source_sha256": self.authority_source_sha256,
            "phase": self.phase.value,
            "rollback_token": self.rollback_token,
            "destination": str(self.destination),
            "source_sha256": self.source_sha256,
            "output_sha256": self.output_sha256,
            "destination_existed": self.destination_existed,
            "destination_sha256": self.destination_sha256,
            "backup": str(self.backup) if self.backup is not None else None,
            "staging": str(self.staging),
            "parent_identity": list(self.parent_identity),
        }


def transaction_id(
    destination: Path, source_sha256: str, request: ExportRequest
) -> str:
    """Compatibility name for the authority-bound export journal key."""
    return authority_digest(destination, source_sha256, request)


def _text(record: dict[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise DocumentError(
            DocumentErrorCode.PRECONDITION_FAILED,
            _STAGE,
            f"export transaction field {field!r} is invalid",
        )
    return value


def _parse(record: dict[str, object]) -> ExportTransaction:
    fields = frozenset(record)
    version = record.get("version")
    if not (
        (fields == _FIELDS and version == _VERSION)
        or (fields == _FIELDS_V1 and version == 1)
    ):
        raise DocumentError(
            DocumentErrorCode.PRECONDITION_FAILED,
            _STAGE,
            "export transaction schema is invalid",
        )
    try:
        phase = ExportPhase(_text(record, "phase"))
    except ValueError as exc:
        raise DocumentError(
            DocumentErrorCode.PRECONDITION_FAILED,
            _STAGE,
            "export transaction phase is invalid",
        ) from exc
    rollback_token = _text(record, "rollback_token")
    try:
        token_valid = uuid.UUID(rollback_token).hex == rollback_token
    except ValueError:
        token_valid = False
    if not token_valid:
        raise DocumentError(
            DocumentErrorCode.PRECONDITION_FAILED,
            _STAGE,
            "export transaction rollback token is invalid",
        )
    existed = record.get("destination_existed")
    prior = record.get("destination_sha256")
    backup_value = record.get("backup")
    if not isinstance(existed, bool) or (
        prior is not None and not isinstance(prior, str)
    ) or (backup_value is not None and not isinstance(backup_value, str)):
        raise DocumentError(
            DocumentErrorCode.PRECONDITION_FAILED,
            _STAGE,
            "export transaction destination state is invalid",
        )
    identity_value = record.get("parent_identity")
    if (
        existed != (prior is not None and backup_value is not None)
        or not isinstance(identity_value, list)
        or len(identity_value) != 2
        or not all(isinstance(item, int) for item in identity_value)
    ):
        raise DocumentError(
            DocumentErrorCode.PRECONDITION_FAILED,
            _STAGE,
            "export transaction rollback state is incomplete",
        )
    parent_identity = tuple(identity_value)
    return ExportTransaction(
        transaction_id=_text(record, "transaction_id"),
        authority_digest=(
            _text(record, "authority_digest")
            if version == _VERSION
            else _text(record, "transaction_id")
        ),
        authority_source_sha256=(
            _text(record, "authority_source_sha256")
            if version == _VERSION
            else _text(record, "source_sha256")
        ),
        authority_bound=version == _VERSION,
        phase=phase,
        rollback_token=rollback_token,
        destination=Path(_text(record, "destination")),
        source_sha256=_text(record, "source_sha256"),
        output_sha256=_text(record, "output_sha256"),
        destination_existed=existed,
        destination_sha256=prior,
        backup=Path(backup_value) if backup_value is not None else None,
        staging=Path(_text(record, "staging")),
        parent_identity=parent_identity,
    )


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

    def load(self, key: str) -> ExportTransaction | None:
        record = read_record(self._path(key), _STAGE)
        if record is None:
            return None
        transaction = _parse(record)
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
            transaction = _parse(record)
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
