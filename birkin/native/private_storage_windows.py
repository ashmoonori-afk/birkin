"""Compatibility re-export for neutral Windows storage primitives."""

from __future__ import annotations

from birkin.private_storage_windows import (
    create_windows_private_temp,
    windows_owner_sid,
)
from birkin.private_storage_windows_handle import open_windows_private_file
from birkin.private_storage_windows_hardening import (
    harden_windows_path_by_handle as harden_windows_path,
)

__all__ = [
    "create_windows_private_temp",
    "harden_windows_path",
    "open_windows_private_file",
    "windows_owner_sid",
]
