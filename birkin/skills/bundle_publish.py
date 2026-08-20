"""Race-safe publication of an already-approved skill bundle."""

from __future__ import annotations

import hashlib
import errno
import os
import secrets
import stat
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .manager import (
    IndeterminatePublicationError,
    PublicationCleanupError,
    _close_preserving_active_error,
    _open_descendant_directory,
    _open_directory_tree,
    _write_all,
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


def snapshot_bundle(root: Path) -> BundleSnapshot:
    directories: list[PurePosixPath] = []
    files: list[BundleFile] = []
    for path in sorted(root.rglob("*")):
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if path.is_symlink():
            raise UnsafeBundleError(relative.as_posix())
        if path.is_dir():
            directories.append(relative)
            continue
        if not path.is_file():
            raise UnsafeBundleError(relative.as_posix())
        status = path.stat()
        files.append(
            BundleFile(
                relative=relative,
                payload=path.read_bytes(),
                mode=stat.S_IMODE(status.st_mode),
            )
        )
    return BundleSnapshot(tuple(directories), tuple(files))


def _populate_posix(root_fd: int, snapshot: BundleSnapshot) -> None:
    for relative in snapshot.directories:
        descriptor = _open_descendant_directory(
            root_fd,
            Path(relative.as_posix()),
            create=True,
        )
        os.close(descriptor)
    for entry in snapshot.files:
        parent = _open_descendant_directory(
            root_fd,
            Path(entry.relative.parent.as_posix()),
            create=True,
        )
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(
                entry.relative.name,
                flags,
                entry.mode,
                dir_fd=parent,
            )
            try:
                _write_all(descriptor, entry.payload)
                os.fchmod(descriptor, entry.mode)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            os.close(parent)


def _rename_noreplace(
    source: str,
    destination: str,
    *,
    source_fd: int,
    destination_fd: int,
) -> None:
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    encoded_source = os.fsencode(source)
    encoded_destination = os.fsencode(destination)
    if sys.platform == "darwin":
        rename = libc.renameatx_np
        result = rename(
            source_fd,
            encoded_source,
            destination_fd,
            encoded_destination,
            0x00000004,
        )
    elif sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise OSError(
                errno.ENOTSUP,
                "renameat2 is unavailable",
            )
        result = rename(
            source_fd,
            encoded_source,
            destination_fd,
            encoded_destination,
            0x00000001,
        )
    else:
        raise OSError(
            errno.ENOTSUP,
            "no-replace directory rename is unavailable",
        )
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination)


def _publish_posix(
    snapshot: BundleSnapshot,
    target: Path,
    target_root: Path,
    replace: bool,
) -> bool:
    root_fd = _open_directory_tree(target_root)
    parent_fd = -1
    operation = f".birkin-sync-{secrets.token_hex(12)}"
    moved_previous = False
    completed = False
    operation_created = False
    try:
        relative = target.relative_to(target_root)
        parent_fd = _open_descendant_directory(
            root_fd,
            relative.parent,
            create=True,
        )
        try:
            os.stat(
                relative.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            exists = True
        except FileNotFoundError:
            exists = False
        if exists and not replace:
            return False
        os.mkdir(operation, 0o700, dir_fd=parent_fd)
        operation_created = True
        operation_fd = _open_descendant_directory(
            parent_fd,
            Path(operation),
        )
        try:
            os.mkdir("candidate", 0o700, dir_fd=operation_fd)
            candidate_fd = _open_descendant_directory(
                operation_fd,
                Path("candidate"),
            )
            try:
                _populate_posix(candidate_fd, snapshot)
            finally:
                os.close(candidate_fd)
            if exists:
                _rename_noreplace(
                    relative.name,
                    "previous",
                    source_fd=parent_fd,
                    destination_fd=operation_fd,
                )
                moved_previous = True
            try:
                _rename_noreplace(
                    "candidate",
                    relative.name,
                    source_fd=operation_fd,
                    destination_fd=parent_fd,
                )
            except OSError:
                if moved_previous:
                    try:
                        _rename_noreplace(
                            "previous",
                            relative.name,
                            source_fd=operation_fd,
                            destination_fd=parent_fd,
                        )
                        moved_previous = False
                    except OSError as rollback_error:
                        raise PublicationCleanupError(
                            relative.as_posix(),
                            snapshot.digest(),
                        ) from rollback_error
                raise PublicationCleanupError(
                    relative.as_posix(),
                    snapshot.digest(),
                )
            if moved_previous:
                moved_previous = False
        finally:
            _close_preserving_active_error(operation_fd)
        try:
            current_parent = _open_descendant_directory(
                root_fd,
                relative.parent,
            )
        except OSError as error:
            raise IndeterminatePublicationError(
                relative.as_posix(),
                snapshot.digest(),
            ) from error
        try:
            if (
                os.fstat(current_parent).st_dev,
                os.fstat(current_parent).st_ino,
            ) != (
                os.fstat(parent_fd).st_dev,
                os.fstat(parent_fd).st_ino,
            ):
                raise IndeterminatePublicationError(
                    relative.as_posix(),
                    snapshot.digest(),
                )
        finally:
            _close_preserving_active_error(current_parent)
        completed = True
        return True
    finally:
        active_error = sys.exc_info()[1]
        close_error: OSError | None = None
        for descriptor in (parent_fd, root_fd):
            if descriptor < 0:
                continue
            try:
                _close_preserving_active_error(descriptor)
            except OSError as error:
                close_error = close_error or error
        if operation_created and not completed and not isinstance(
            active_error,
            (
                IndeterminatePublicationError,
                PublicationCleanupError,
            ),
        ):
            raise PublicationCleanupError(
                target.name,
                snapshot.digest(),
            ) from active_error
        if active_error is None and close_error is not None:
            raise close_error


def publish_bundle(
    snapshot: BundleSnapshot,
    target: Path,
    *,
    target_root: Path,
    replace: bool,
) -> bool:
    if os.name == "nt":
        from .bundle_publish_windows import publish_windows
        return publish_windows(snapshot, target, target_root, replace)
    return _publish_posix(snapshot, target, target_root, replace)
