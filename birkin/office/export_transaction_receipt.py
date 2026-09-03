"""Immutable authenticated receipts for export transactions."""

from __future__ import annotations

from pathlib import Path

from .errors import DocumentError, DocumentErrorCode
from .export_io import recovery_error
from .export_journal_record import ExportTransaction
from .export_types import ExportReceipt, ExportRequest
from .proposal_integrity import authority_digest
from .receipt_auth import (
    authenticate_receipt,
    receipt_window,
    sign_receipt,
    verified_receipt_window,
)


def transaction_receipt(
    transaction: ExportTransaction,
    request: ExportRequest,
) -> ExportReceipt:
    if transaction.receipt_authenticated and (
        transaction.receipt_issued_at is None
        or transaction.receipt_expires_at is None
        or transaction.receipt_hmac is None
    ):
        raise recovery_error("export receipt seal is unavailable")
    return ExportReceipt(
        rollback_token=transaction.rollback_token,
        authority_digest=transaction.authority_digest,
        authority_source_sha256=transaction.authority_source_sha256,
        authority_bound=True,
        receipt_authenticated=transaction.receipt_authenticated,
        issued_at=transaction.receipt_issued_at or "",
        expires_at=transaction.receipt_expires_at or "",
        receipt_hmac=transaction.receipt_hmac or "",
        destination=transaction.destination,
        source_sha256=transaction.source_sha256,
        output_sha256=transaction.output_sha256,
        operations=tuple(dict(operation) for operation in request.operations),
        actor=request.actor,
        proposal_digest=request.proposal_digest,
        overwrite_approved=request.overwrite_approved,
        destination_existed=transaction.destination_existed,
        destination_sha256=transaction.destination_sha256,
        backup=transaction.backup,
    )


def seal_transaction_receipt(
    transaction: ExportTransaction,
    request: ExportRequest,
    office_home: Path,
    *,
    enforce_retention: bool = True,
) -> ExportTransaction:
    if not transaction.receipt_authenticated:
        return transaction
    if transaction.receipt_hmac is not None:
        payload = transaction_receipt(transaction, request).public()
        if not enforce_retention:
            # An unfinished transaction stays resumable past its receipt window.
            _ = verified_receipt_window(payload, office_home)
            return transaction
        authenticated = authenticate_receipt(payload, office_home)
        if not authenticated:
            raise recovery_error("export receipt authentication is unavailable")
        return transaction
    issued_at, expires_at = receipt_window()
    provisional = transaction.seal_receipt(issued_at, expires_at, "")
    receipt = transaction_receipt(provisional, request)
    return transaction.seal_receipt(
        issued_at,
        expires_at,
        sign_receipt(receipt.authenticated_payload(), office_home),
    )


def approved_export_authority(
    destination: Path,
    export_source_sha256: str,
    request: ExportRequest,
) -> tuple[str, str]:
    source_sha256 = request.authority_source_sha256 or export_source_sha256
    expected = authority_digest(destination, source_sha256, request)
    if request.authority_digest is not None and (
        request.authority_digest != expected
    ):
        raise DocumentError(
            DocumentErrorCode.POLICY_DENIED,
            "export",
            "export request authority digest changed",
        )
    return expected, source_sha256
