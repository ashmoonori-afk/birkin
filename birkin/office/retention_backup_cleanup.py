"""Authenticated quarantine before Office backup deletion."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from .export_io import recovery_error, regular_file_identity
from .export_no_replace_move import move_no_replace
from .export_open_descriptor import open_export_descriptor
from .path_identity import descriptor_identity
from .path_security import hash_descriptor


def receipt_backup_hash(receipt: Mapping[str, object]) -> str | None:
    digest = receipt.get("destination_sha256")
    return digest if isinstance(digest, str) else None


def remove_authenticated_backup(
    backup: Path,
    expected_sha256: str,
) -> int:
    quarantine = backup.with_name(f".{backup.name}.purge")
    if quarantine.exists() or quarantine.is_symlink():
        if backup.exists() or backup.is_symlink():
            raise recovery_error(
                "export backup and purge quarantine both exist",
                "office_retention",
            )
        return _finish_quarantine(quarantine, expected_sha256)
    try:
        descriptor = open_export_descriptor(
            backup,
            writable=False,
        )
    except FileNotFoundError:
        return 0
    try:
        identity = descriptor_identity(descriptor)
        if hash_descriptor(descriptor) != expected_sha256:
            raise recovery_error(
                "export backup differs from authenticated rollback material",
                "office_retention",
            )
        move_no_replace(backup, quarantine)
        if (
            regular_file_identity(quarantine) != identity
            or hash_descriptor(descriptor) != expected_sha256
        ):
            raise recovery_error(
                "export backup changed during quarantine",
                "office_retention",
            )
    except OSError as exc:
        raise recovery_error(
            "export backup quarantine must finish",
            "office_retention",
        ) from exc
    finally:
        os.close(descriptor)
    return _finish_quarantine(quarantine, expected_sha256)


def _finish_quarantine(
    quarantine: Path,
    expected_sha256: str,
) -> int:
    descriptor = open_export_descriptor(
        quarantine,
        writable=True,
    )
    try:
        identity = descriptor_identity(descriptor)
        metadata = os.fstat(descriptor)
        if metadata.st_size == 0:
            return 1
        if (
            hash_descriptor(descriptor) != expected_sha256
            or regular_file_identity(quarantine) != identity
        ):
            raise recovery_error(
                "quarantined export backup changed",
                "office_retention",
            )
        os.ftruncate(descriptor, 0)
        os.fsync(descriptor)
    except OSError as exc:
        raise recovery_error(
            "export backup deletion must finish",
            "office_retention",
        ) from exc
    finally:
        os.close(descriptor)
    return 1
