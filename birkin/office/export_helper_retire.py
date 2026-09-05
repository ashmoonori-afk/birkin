"""Descriptor-bound retirement for authenticated export helper bytes."""

from __future__ import annotations

import os
from pathlib import Path

from .export_io import recovery_error, regular_file_identity
from .export_open_descriptor import open_export_descriptor
from .export_quarantine_retire import retire_bound_path
from .path_identity import descriptor_identity
from .path_security import hash_descriptor
from .retirement_sweep import (
    authenticate_retired_file,
    sweep_retirement_quarantine,
)


def retire_authenticated_file(
    path: Path,
    expected_sha256: str,
    *,
    expected_identity: tuple[int, int] | None = None,
    protected_identity: tuple[int, int] | None = None,
    required: bool = True,
) -> bool:
    # Startup recovery: bound authenticated residue left by an earlier crash.
    _ = sweep_retirement_quarantine(path.parent)
    try:
        descriptor = open_export_descriptor(
            path,
            writable=True,
        )
    except FileNotFoundError:
        return False
    try:
        metadata = os.fstat(descriptor)
        identity = descriptor_identity(descriptor)
        if protected_identity is not None and identity == protected_identity:
            return False
        valid = (
            (expected_identity is None or identity == expected_identity)
            and (
                metadata.st_size == 0
                or hash_descriptor(descriptor) == expected_sha256
            )
            and regular_file_identity(path) == identity
        )
        if not valid:
            if required:
                raise recovery_error(
                    "export helper changed before retirement"
                )
            return False
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        retire_bound_path(path, descriptor, identity)
        if os.name != "nt":
            authenticate_retired_file(path.parent, identity, expected_sha256)
            # Post-retention sweep enforces caps after this payload is visible.
            _ = sweep_retirement_quarantine(path.parent)
        return True
    finally:
        os.close(descriptor)
