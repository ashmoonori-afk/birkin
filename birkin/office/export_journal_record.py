"""Versioned export transaction records."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from .errors import DocumentError, DocumentErrorCode

_STAGE = "office_export_journal"
_VERSION = 4
_FIELDS_V1 = frozenset(
    {
        "version", "transaction_id", "phase", "rollback_token", "destination",
        "source_sha256", "output_sha256", "destination_existed",
        "destination_sha256", "backup", "staging", "parent_identity",
    }
)
_FIELDS_V2 = _FIELDS_V1 | {
    "authority_digest",
    "authority_source_sha256",
}
_FIELDS_V3 = _FIELDS_V2 | {"receipt_authenticated"}
_FIELDS = _FIELDS_V3 | {
    "receipt_issued_at",
    "receipt_expires_at",
    "receipt_hmac",
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
    receipt_authenticated: bool
    receipt_issued_at: str | None
    receipt_expires_at: str | None
    receipt_hmac: str | None
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

    def seal_receipt(
        self,
        issued_at: str,
        expires_at: str,
        signature: str,
    ) -> ExportTransaction:
        return replace(
            self,
            receipt_issued_at=issued_at,
            receipt_expires_at=expires_at,
            receipt_hmac=signature,
        )

    def record(self) -> dict[str, object]:
        return {
            "version": _VERSION,
            "transaction_id": self.transaction_id,
            "authority_digest": self.authority_digest,
            "authority_source_sha256": self.authority_source_sha256,
            "receipt_authenticated": self.receipt_authenticated,
            "receipt_issued_at": self.receipt_issued_at,
            "receipt_expires_at": self.receipt_expires_at,
            "receipt_hmac": self.receipt_hmac,
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


def _text(record: dict[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise _error(f"export transaction field {field!r} is invalid")
    return value


def parse_transaction(record: dict[str, object]) -> ExportTransaction:
    fields = frozenset(record)
    version = _version(record.get("version"))
    if not (
        (fields == _FIELDS and version == _VERSION)
        or (fields == _FIELDS_V3 and version == 3)
        or (fields == _FIELDS_V2 and version == 2)
        or (fields == _FIELDS_V1 and version == 1)
    ):
        raise _error("export transaction schema is invalid")
    try:
        phase = ExportPhase(_text(record, "phase"))
    except ValueError as exc:
        raise _error("export transaction phase is invalid") from exc
    rollback_token = _text(record, "rollback_token")
    try:
        token_valid = uuid.UUID(rollback_token).hex == rollback_token
    except ValueError:
        token_valid = False
    if not token_valid:
        raise _error("export transaction rollback token is invalid")
    existed = record.get("destination_existed")
    prior_value = record.get("destination_sha256")
    prior = (
        _digest_value(prior_value, "destination_sha256")
        if prior_value is not None
        else None
    )
    backup_value = record.get("backup")
    if (
        not isinstance(existed, bool)
        or (backup_value is not None and not isinstance(backup_value, str))
        or existed != (prior is not None and backup_value is not None)
    ):
        raise _error("export transaction rollback state is incomplete")
    parent_identity = _parent_identity(record.get("parent_identity"))
    receipt_authenticated = record.get("receipt_authenticated", False)
    if not isinstance(receipt_authenticated, bool):
        raise _error("export transaction receipt authority is invalid")
    seal = _receipt_seal(record, version, receipt_authenticated)
    authority_versions = {2, 3, _VERSION}
    return ExportTransaction(
        transaction_id=_digest(record, "transaction_id"),
        authority_digest=(
            _digest(record, "authority_digest")
            if version in authority_versions
            else _digest(record, "transaction_id")
        ),
        authority_source_sha256=(
            _digest(record, "authority_source_sha256")
            if version in authority_versions
            else _digest(record, "source_sha256")
        ),
        authority_bound=version in authority_versions,
        receipt_authenticated=receipt_authenticated,
        receipt_issued_at=seal[0],
        receipt_expires_at=seal[1],
        receipt_hmac=seal[2],
        phase=phase,
        rollback_token=rollback_token,
        destination=Path(_text(record, "destination")),
        source_sha256=_digest(record, "source_sha256"),
        output_sha256=_digest(record, "output_sha256"),
        destination_existed=existed,
        destination_sha256=prior,
        backup=Path(backup_value) if backup_value is not None else None,
        staging=Path(_text(record, "staging")),
        parent_identity=parent_identity,
    )


def _receipt_seal(
    record: dict[str, object],
    version: object,
    authenticated: bool,
) -> tuple[str | None, str | None, str | None]:
    if version != _VERSION:
        if authenticated:
            raise _error(
                "legacy export transaction cannot gain receipt authority"
            )
        return None, None, None
    issued = record.get("receipt_issued_at")
    expires = record.get("receipt_expires_at")
    signature = record.get("receipt_hmac")
    if authenticated:
        if not isinstance(issued, str) or not issued:
            raise _error("export transaction receipt seal is invalid")
        if not isinstance(expires, str) or not expires:
            raise _error("export transaction receipt seal is invalid")
        return issued, expires, _digest_value(signature, "receipt_hmac")
    if issued is not None or expires is not None or signature is not None:
        raise _error("export transaction receipt seal is invalid")
    return None, None, None


def _parent_identity(value: object) -> tuple[int, int]:
    match value:
        case [int(first), int(second)]:
            if isinstance(first, bool) or isinstance(second, bool):
                raise _error("export transaction directory identity is invalid")
            return first, second
        case _:
            raise _error("export transaction directory identity is invalid")


def _version(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _error("export transaction version is invalid")
    return value


def _digest(record: dict[str, object], field: str) -> str:
    return _digest_value(record.get(field), field)


def _digest_value(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _error(f"export transaction field {field!r} is invalid")
    return value


def _error(message: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.PRECONDITION_FAILED,
        _STAGE,
        message,
    )
