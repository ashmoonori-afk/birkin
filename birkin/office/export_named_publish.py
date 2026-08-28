"""Portable independent-inode publication when native cloning is unavailable."""

from __future__ import annotations

import errno
import os
from pathlib import Path

from .export_descriptor_copy import copy_descriptor
from .export_io import regular_file_identity
from .export_no_replace_move import move_no_replace
from .export_open_descriptor import create_export_descriptor
from .export_quarantine_retire import retire_bound_path
from .path_identity import descriptor_identity


def publish_named_copy(
    source_descriptor: int,
    destination: Path,
) -> None:
    temporary, descriptor = _create_temporary(destination)
    moved = False
    expected_identity = descriptor_identity(descriptor)
    try:
        copy_descriptor(source_descriptor, descriptor)
        os.fsync(descriptor)
        if descriptor_identity(descriptor) != expected_identity:
            raise OSError(
                errno.ESTALE,
                "named export inode changed during copy",
                temporary,
            )
        move_no_replace(temporary, destination)
        moved = True
        if descriptor_identity(descriptor) != expected_identity:
            raise OSError(
                errno.ESTALE,
                "named export inode changed during publication",
                destination,
            )
        if regular_file_identity(destination) != expected_identity:
            raise OSError(
                errno.ESTALE,
                "named export path changed during publication",
                destination,
            )
    finally:
        if not moved:
            os.ftruncate(descriptor, 0)
            os.fsync(descriptor)
            retire_bound_path(
                temporary,
                descriptor,
                expected_identity,
            )
        os.close(descriptor)


def _create_temporary(destination: Path) -> tuple[Path, int]:
    temporary = destination.with_name(
        f".{destination.name}.birkin-publish"
    )
    return temporary, create_export_descriptor(temporary)
