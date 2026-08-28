"""No-replace restoration of an authenticated export displacement."""

from __future__ import annotations

import os
from pathlib import Path

from .export_inode_publish import publish_open_file
from .export_io import current_hash, recovery_error, regular_file_identity
from .export_open_descriptor import open_export_descriptor
from .path_identity import descriptor_identity
from .path_security import hash_descriptor


def restore_displaced(
    checkpoint: Path,
    destination: Path,
    expected_sha256: str,
) -> None:
    descriptor = open_export_descriptor(
        checkpoint,
        writable=True,
    )
    try:
        checkpoint_identity = descriptor_identity(descriptor)
        if hash_descriptor(descriptor) != expected_sha256:
            raise recovery_error("export displacement checkpoint changed")
        current = current_hash(destination)
        if current is None:
            try:
                published_identity = publish_open_file(
                    descriptor,
                    destination,
                )
            except FileExistsError as exc:
                raise recovery_error(
                    "export displacement restoration was occupied"
                ) from exc
            if (
                regular_file_identity(destination) != published_identity
                or current_hash(destination) != expected_sha256
            ):
                raise recovery_error(
                    "restored export displacement changed"
                )
        elif current != expected_sha256:
            raise recovery_error(
                "export displacement restoration was occupied"
            )
        else:
            published_identity = regular_file_identity(destination)
        if (
            regular_file_identity(checkpoint) != checkpoint_identity
            or hash_descriptor(descriptor) != expected_sha256
        ):
            raise recovery_error("export displacement checkpoint changed")
        if published_identity != checkpoint_identity:
            os.ftruncate(descriptor, 0)
            os.fsync(descriptor)
    finally:
        os.close(descriptor)
