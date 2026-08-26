"""Compatibility re-export for owner-only storage primitives."""

from __future__ import annotations

from birkin.private_storage import (
    create_private_temp,
    harden_private_directory,
    harden_private_file,
    open_private_file_for_read,
)
from birkin.private_storage_windows import windows_owner_sid

_windows_owner_sid = windows_owner_sid

__all__ = [
    "create_private_temp",
    "harden_private_directory",
    "harden_private_file",
    "open_private_file_for_read",
]
