"""Platform-specific primitives for durable, no-overwrite artifact publication."""

from __future__ import annotations

import os
from pathlib import Path

from . import windows_native
from .path_security import (
    canonical_name,
    ensure_open_identity,
    ensure_path_identity,
    regular_path_identity,
)


def collision(directory_handle: int, drafts: Path, wanted: str) -> bool:
    directory: int | Path = drafts if os.name == "nt" else directory_handle
    return any(canonical_name(name) == wanted for name in os.listdir(directory))


def published_matches(
    directory_handle: int,
    drafts: Path,
    name: str,
    expected: tuple[int, int] | None,
) -> bool:
    if os.name == "nt":
        return expected == regular_path_identity(drafts / name)
    metadata = os.stat(name, dir_fd=directory_handle, follow_symlinks=False)
    return expected == (metadata.st_dev, metadata.st_ino)


def ensure_temporary_identity(
    descriptor: int,
    temporary_name: str,
    directory_handle: int,
    drafts: Path,
) -> None:
    if os.name == "nt":
        ensure_path_identity(descriptor, drafts / temporary_name)
    else:
        ensure_open_identity(descriptor, temporary_name, directory_handle)


def link_temporary(
    temporary_name: str,
    output_name: str,
    directory_handle: int,
    drafts: Path,
) -> None:
    if os.name == "nt":
        os.link(drafts / temporary_name, drafts / output_name)
    else:
        os.link(
            temporary_name,
            output_name,
            src_dir_fd=directory_handle,
            dst_dir_fd=directory_handle,
            follow_symlinks=False,
        )


def unlink(name: str, directory_handle: int, drafts: Path) -> None:
    if os.name == "nt":
        (drafts / name).unlink()
    else:
        os.unlink(name, dir_fd=directory_handle)


def sync_publication(directory_handle: int, descriptor: int) -> None:
    if os.name == "nt":
        os.fsync(descriptor)
    else:
        os.fsync(directory_handle)


def sync_cleanup(directory_handle: int) -> None:
    if os.name != "nt":
        os.fsync(directory_handle)


def acquire_publication_lock(
    directory_handle: int, identity: tuple[int, int]
) -> int:
    if os.name == "nt":
        return windows_native.acquire_publication_mutex(identity)
    import fcntl

    fcntl.flock(directory_handle, fcntl.LOCK_EX)
    return -1


def release_publication_lock(directory_handle: int, lock_handle: int) -> None:
    if os.name == "nt":
        windows_native.release_publication_mutex(lock_handle)
        return
    import fcntl

    fcntl.flock(directory_handle, fcntl.LOCK_UN)


def temporary_path_matches(path: Path, expected: tuple[int, int] | None) -> bool:
    if os.name == "nt":
        return regular_path_identity(path) == expected
    metadata = path.stat(follow_symlinks=False)
    return expected == (metadata.st_dev, metadata.st_ino)
