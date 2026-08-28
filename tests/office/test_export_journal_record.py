from __future__ import annotations

from copy import deepcopy

import pytest

from birkin.office.errors import DocumentError
from birkin.office.export_journal_record import parse_transaction


def _v4_record() -> dict[str, object]:
    return {
        "version": 4,
        "transaction_id": "a" * 64,
        "authority_digest": "b" * 64,
        "authority_source_sha256": "c" * 64,
        "receipt_authenticated": True,
        "receipt_issued_at": "2026-01-01T00:00:00Z",
        "receipt_expires_at": "2026-01-31T00:00:00Z",
        "receipt_hmac": "d" * 64,
        "phase": "committed",
        "rollback_token": "e" * 32,
        "destination": "/tmp/result.txt",
        "source_sha256": "f" * 64,
        "output_sha256": "f" * 64,
        "destination_existed": False,
        "destination_sha256": None,
        "backup": None,
        "staging": "/tmp/.staging",
        "parent_identity": [1, 2],
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", 4.0),
        ("parent_identity", [True, 2]),
        ("receipt_hmac", "d"),
        ("source_sha256", "F" * 64),
    ],
)
def test_v4_export_record_rejects_ambiguous_scalar_types(
    field: str,
    value: object,
) -> None:
    record = _v4_record()
    record[field] = value

    with pytest.raises(DocumentError):
        _ = parse_transaction(record)


def test_v1_export_record_rejects_boolean_version() -> None:
    record = deepcopy(_v4_record())
    for field in (
        "authority_digest",
        "authority_source_sha256",
        "receipt_authenticated",
        "receipt_issued_at",
        "receipt_expires_at",
        "receipt_hmac",
    ):
        del record[field]
    record["version"] = True

    with pytest.raises(DocumentError):
        _ = parse_transaction(record)


def test_v3_export_record_cannot_gain_new_receipt_authority() -> None:
    record = _v4_record()
    for field in (
        "receipt_issued_at",
        "receipt_expires_at",
        "receipt_hmac",
    ):
        del record[field]
    record["version"] = 3

    with pytest.raises(DocumentError, match="cannot gain receipt authority"):
        _ = parse_transaction(record)
