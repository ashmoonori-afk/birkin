"""Recoverable compare-and-displace publication for caller destinations."""

from __future__ import annotations

import os
from pathlib import Path

from .errors import DocumentError, DocumentErrorCode
from .export_compensation import compensate_export
from .export_displacement_restore import restore_displaced
from .export_helper_retire import retire_authenticated_file
from .export_io import (
    DirectorySync,
    current_hash,
    hash_file as _hash_file,
    recovery_error,
    regular_file_identity,
    reservation_hash,
)
from .export_inode_publish import publish_open_file as _publish_open_file
from .export_journal_record import ExportTransaction
from .export_no_replace_move import move_no_replace
from .export_open_descriptor import open_export_descriptor
from .path_identity import descriptor_identity
from .path_security import hash_descriptor as _hash_descriptor


def publication_file_hash(path: Path) -> str:
    return _hash_file(path)


def publication_descriptor_hash(descriptor: int) -> str:
    return _hash_descriptor(descriptor)


def publication_from_descriptor(
    descriptor: int,
    destination: Path,
) -> tuple[int, int]:
    return _publish_open_file(descriptor, destination)


def publish_staged(
    transaction: ExportTransaction,
    staging_identity: tuple[int, int],
    sync_directory: DirectorySync,
) -> None:
    checkpoint = _checkpoint(transaction)
    expected = _expected_prior(transaction)
    published_identity: tuple[int, int] | None = None
    try:
        if checkpoint.exists() or checkpoint.is_symlink():
            _require_checkpoint(checkpoint, expected)
        else:
            try:
                move_no_replace(transaction.destination, checkpoint)
            except FileExistsError as exc:
                raise recovery_error(
                    "export displacement checkpoint is occupied"
                ) from exc
            if checkpoint.is_symlink() or not checkpoint.is_file():
                raise recovery_error(
                    "export displacement checkpoint changed"
                )
            displaced_sha256 = publication_file_hash(checkpoint)
            if displaced_sha256 != expected:
                restore_displaced(
                    checkpoint,
                    transaction.destination,
                    displaced_sha256,
                )
                raise _changed("destination changed during atomic displacement")
        current = current_hash(transaction.destination)
        if current is None:
            published_identity = _publish_staging(
                transaction,
                staging_identity,
            )
            if (
                transaction.staging.is_symlink()
                or regular_file_identity(transaction.staging)
                != staging_identity
            ):
                raise _changed(
                    "staged export changed during atomic publication"
                )
        elif current != transaction.output_sha256:
            raise _changed("destination was occupied during atomic publication")
        else:
            published_identity = regular_file_identity(
                transaction.destination
            )
        _require_published(transaction, published_identity)
        sync_directory(
            transaction.destination.parent,
            transaction.parent_identity,
        )
        _require_published(transaction, published_identity)
        _ = retire_authenticated_file(checkpoint, expected)
        sync_directory(
            transaction.destination.parent,
            transaction.parent_identity,
        )
        _ = retire_authenticated_file(
            transaction.staging,
            transaction.output_sha256,
            expected_identity=staging_identity,
            protected_identity=published_identity,
            required=False,
        )
    except DocumentError:
        compensate_export(
            transaction,
            checkpoint,
            expected,
            sync_directory,
        )
        raise
    except OSError as exc:
        if (
            not checkpoint.exists()
            and not checkpoint.is_symlink()
            and current_hash(transaction.destination)
            == transaction.output_sha256
        ):
            raise recovery_error(
                "atomic export checkpoint durability must finish"
            ) from exc
        compensate_export(
            transaction,
            checkpoint,
            expected,
            sync_directory,
        )
        raise recovery_error("atomic export publication must finish") from exc


def finish_published_checkpoint(
    transaction: ExportTransaction,
    sync_directory: DirectorySync,
) -> None:
    checkpoint = _checkpoint(transaction)
    if not checkpoint.exists() and not checkpoint.is_symlink():
        return
    if checkpoint.is_file() and checkpoint.stat().st_size == 0:
        return
    _require_checkpoint(checkpoint, _expected_prior(transaction))
    if current_hash(transaction.destination) != transaction.output_sha256:
        raise _changed("published destination changed before checkpoint cleanup")
    try:
        _ = retire_authenticated_file(
            checkpoint,
            _expected_prior(transaction),
            protected_identity=regular_file_identity(
                transaction.destination
            ),
        )
        sync_directory(
            transaction.destination.parent,
            transaction.parent_identity,
        )
    except OSError as exc:
        raise recovery_error("export displacement cleanup must finish") from exc


def has_valid_displacement(transaction: ExportTransaction) -> bool:
    checkpoint = _checkpoint(transaction)
    return (
        (checkpoint.exists() or checkpoint.is_symlink())
        and _checkpoint_matches(checkpoint, _expected_prior(transaction))
    )


def _publish_staging(
    transaction: ExportTransaction,
    staging_identity: tuple[int, int],
) -> tuple[int, int]:
    if (
        transaction.staging.is_symlink()
        or regular_file_identity(transaction.staging) != staging_identity
    ):
        raise _changed("staged export changed before atomic publication")
    descriptor = open_export_descriptor(
        transaction.staging,
        writable=False,
    )
    try:
        if (
            descriptor_identity(descriptor) != staging_identity
            or publication_descriptor_hash(descriptor)
            != transaction.output_sha256
        ):
            raise _changed("staged export changed before atomic publication")
        return publication_from_descriptor(
            descriptor,
            transaction.destination,
        )
    except FileExistsError as exc:
        raise _changed("destination was occupied during atomic publication") from exc
    finally:
        os.close(descriptor)


def _require_published(
    transaction: ExportTransaction,
    published_identity: tuple[int, int] | None,
) -> None:
    if (
        published_identity is None
        or transaction.destination.is_symlink()
        or regular_file_identity(transaction.destination)
        != published_identity
        or current_hash(transaction.destination) != transaction.output_sha256
    ):
        raise _changed("published export differs from validated staging")


def _checkpoint(transaction: ExportTransaction) -> Path:
    return transaction.staging.with_name(
        f"{transaction.staging.name}.displaced"
    )


def _expected_prior(transaction: ExportTransaction) -> str:
    if transaction.destination_existed:
        prior = transaction.destination_sha256
        if prior is None:
            raise recovery_error("export destination proof is incomplete")
        return prior
    return reservation_hash(transaction)


def _require_checkpoint(checkpoint: Path, expected: str) -> None:
    if not _checkpoint_matches(checkpoint, expected):
        raise recovery_error("export displacement checkpoint changed")


def _checkpoint_matches(checkpoint: Path, expected: str) -> bool:
    return (
        not checkpoint.is_symlink()
        and checkpoint.is_file()
        and publication_file_hash(checkpoint) == expected
    )


def _changed(message: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.SOURCE_CHANGED,
        "export",
        message,
    )
