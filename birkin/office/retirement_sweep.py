"""Bound sensitive bytes in the authenticated Office retirement quarantine.

POSIX cannot provide an inode-bound unlink.  This module therefore never claims
physical secure erasure and never pathname-unlinks a candidate.  It opens
no-follow, authenticates the digest encoded at retirement, checks the bound
identity again, and truncates that descriptor.  Empty owner-only tombstones may
remain and are reported truthfully; sensitive payload age, count, and bytes are
bounded.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import time
from pathlib import Path
from typing import TypedDict

DEFAULT_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
DEFAULT_MAX_ITEMS = 32
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
MAX_DIAGNOSTICS = 8
_AUTHENTICATED_NAME = re.compile(r"^retired-([0-9a-f]{64})-([0-9a-f]{32})$")


class SweepReceipt(TypedDict):
    payload_items: int
    payload_bytes: int
    tombstones: int
    retired: int
    tampered: int
    unsafe: int
    secure_erasure: bool
    diagnostics: list[str]


def _diagnose(receipt: SweepReceipt, message: str) -> None:
    if len(receipt["diagnostics"]) < MAX_DIAGNOSTICS:
        receipt["diagnostics"].append(message)


def authenticate_retired_file(
    parent: Path,
    identity: tuple[int, int],
    expected_sha256: str,
) -> None:
    """Give the newly retired inode an authenticated, unpredictable name."""
    quarantine = parent / ".birkin-retire"
    directory = os.open(quarantine, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_DIRECTORY", 0)
                        | getattr(os, "O_NOFOLLOW", 0))
    try:
        for name in os.listdir(directory):
            if not name.startswith("retired-") or _AUTHENTICATED_NAME.fullmatch(name):
                continue
            try:
                metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISREG(metadata.st_mode) and (
                    metadata.st_dev, metadata.st_ino) == identity:
                authenticated = f"retired-{expected_sha256}-{secrets.token_hex(16)}"
                os.rename(name, authenticated, src_dir_fd=directory,
                          dst_dir_fd=directory)
                os.fsync(directory)
                return
        raise OSError("retired Office object identity is unavailable")
    finally:
        os.close(directory)


def _hash_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    _ = os.lseek(descriptor, 0, os.SEEK_SET)
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    _ = os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest()


def sweep_retirement_quarantine(
    parent: Path,
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    now: float | None = None,
) -> SweepReceipt:
    """Bound authenticated payloads and return a bounded residue receipt."""
    receipt: SweepReceipt = {"payload_items": 0, "payload_bytes": 0,
        "tombstones": 0, "retired": 0, "tampered": 0, "unsafe": 0,
        "secure_erasure": False, "diagnostics": []}
    quarantine = parent / ".birkin-retire"
    try:
        directory = os.open(quarantine, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
                            | getattr(os, "O_DIRECTORY", 0)
                            | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return receipt
    except OSError:
        receipt["unsafe"] += 1
        _diagnose(receipt, "retirement quarantine is unavailable")
        return receipt
    current = time.time() if now is None else now
    candidates: list[tuple[float, str, int, tuple[int, int]]] = []
    try:
        metadata = os.fstat(directory)
        if (not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) & 0o077):
            receipt["unsafe"] += 1
            _diagnose(receipt, "retirement quarantine is not owner-only")
            return receipt
        for name in os.listdir(directory):
            match = _AUTHENTICATED_NAME.fullmatch(name)
            if match is None:
                receipt["unsafe"] += 1
                _diagnose(receipt, "unmanaged retirement residue remains")
                continue
            flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(name, flags, dir_fd=directory)
            except OSError:
                receipt["unsafe"] += 1
                _diagnose(receipt, "retirement residue could not be opened safely")
                continue
            try:
                opened = os.fstat(descriptor)
                identity = (opened.st_dev, opened.st_ino)
                current_path = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (not stat.S_ISREG(opened.st_mode) or identity !=
                        (current_path.st_dev, current_path.st_ino)):
                    receipt["unsafe"] += 1
                    _diagnose(receipt, "retirement residue identity changed")
                    continue
                if opened.st_size == 0:
                    receipt["tombstones"] += 1
                    continue
                if _hash_descriptor(descriptor) != match.group(1):
                    receipt["tampered"] += 1
                    _diagnose(receipt, "retirement residue authentication mismatch")
                    continue
                candidates.append((opened.st_mtime, name, opened.st_size, identity))
            finally:
                os.close(descriptor)
        candidates.sort(reverse=True)
        kept_items = kept_bytes = 0
        for modified, name, size, identity in candidates:
            retain = (current - modified <= max_age_seconds
                      and kept_items < max_items and kept_bytes + size <= max_bytes)
            if retain:
                kept_items += 1
                kept_bytes += size
                continue
            descriptor = -1
            try:
                descriptor = os.open(name, os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
                                     | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory)
                opened = os.fstat(descriptor)
                path_now = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if ((opened.st_dev, opened.st_ino) != identity
                        or identity != (path_now.st_dev, path_now.st_ino)
                        or opened.st_nlink != 1):
                    receipt["unsafe"] += 1
                    _diagnose(receipt, "retirement residue changed before sweep")
                    continue
                os.ftruncate(descriptor, 0)
                os.fsync(descriptor)
                receipt["retired"] += 1
                receipt["tombstones"] += 1
            except OSError:
                receipt["unsafe"] += 1
                _diagnose(receipt, "retirement residue could not be bounded")
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        os.fsync(directory)
        receipt["payload_items"] = kept_items
        receipt["payload_bytes"] = kept_bytes
        return receipt
    finally:
        os.close(directory)
