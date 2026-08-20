"""Immutable, no-follow snapshots of staged skill bundles."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .manager import (
    _close_preserving_active_error,
    _open_descendant_directory,
    _open_directory_tree,
)


class UnsafeBundleError(ValueError):
    """The staged bundle cannot be represented without following a link."""


@dataclass(frozen=True, slots=True)
class BundleFile:
    relative: PurePosixPath
    payload: bytes
    mode: int


@dataclass(frozen=True, slots=True)
class BundleSnapshot:
    directories: tuple[PurePosixPath, ...]
    files: tuple[BundleFile, ...]

    def file_overrides(self) -> dict[str, bytes]:
        return {
            entry.relative.as_posix(): entry.payload
            for entry in self.files
        }

    def digest(self) -> str:
        digest = hashlib.sha256()

        def update(payload: bytes) -> None:
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)

        for directory in self.directories:
            digest.update(b"d")
            update(directory.as_posix().encode("utf-8"))
        for entry in self.files:
            digest.update(b"f")
            update(entry.relative.as_posix().encode("utf-8"))
            update(entry.mode.to_bytes(4, "big"))
            update(entry.payload)
        return digest.hexdigest()


def _read_posix_file(
    root_fd: int,
    relative: PurePosixPath,
) -> tuple[bytes, int]:
    parent_fd = _open_descendant_directory(
        root_fd,
        Path(relative.parent.as_posix()),
    )
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(
            relative.name,
            flags,
            dir_fd=parent_fd,
        )
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise UnsafeBundleError(relative.as_posix())
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 64 * 1024):
            chunks.append(chunk)
        return b"".join(chunks), stat.S_IMODE(status.st_mode)
    finally:
        if descriptor >= 0:
            _close_preserving_active_error(descriptor)
        _close_preserving_active_error(parent_fd)


def snapshot_bundle(root: Path) -> BundleSnapshot:
    if root.is_symlink():
        raise UnsafeBundleError(root.name)
    root = root.resolve()
    directories: list[PurePosixPath] = []
    files: list[BundleFile] = []
    root_fd = (
        None
        if os.name == "nt"
        else _open_directory_tree(root)
    )
    try:
        for path in sorted(root.rglob("*")):
            relative = PurePosixPath(
                path.relative_to(root).as_posix()
            )
            if path.is_symlink():
                raise UnsafeBundleError(relative.as_posix())
            if path.is_dir():
                directories.append(relative)
                continue
            if not path.is_file():
                raise UnsafeBundleError(relative.as_posix())
            if root_fd is None:
                status = path.stat()
                payload = path.read_bytes()
                mode = stat.S_IMODE(status.st_mode)
            else:
                payload, mode = _read_posix_file(
                    root_fd,
                    relative,
                )
            files.append(
                BundleFile(
                    relative=relative,
                    payload=payload,
                    mode=mode,
                )
            )
    finally:
        if root_fd is not None:
            _close_preserving_active_error(root_fd)
    return BundleSnapshot(tuple(directories), tuple(files))
