"""Crash-atomic replacement after descriptor-bound authorization."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import secrets

from ..office.export_no_replace_move import exchange_between
from ..office.export_quarantine_retire import retire_bound_path
from .file_target import (
    OpenedTarget,
    PathPolicy,
    UnsafeTargetError,
    close_target,
    descriptor_final_path,
)


def replace_bytes_atomic(
    target: OpenedTarget,
    payload: bytes,
    policy: PathPolicy,
) -> None:
    if os.name == "nt":
        _replace_windows(target, payload, policy)
        return
    parent = os.open(
        target.final_path.parent,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    temporary = (
        f".{target.final_path.name}.birkin-edit-{secrets.token_hex(8)}"
    )
    descriptor = -1
    exchanged = False
    published = False
    final_parent = target.final_path.parent
    try:
        final_parent = descriptor_final_path(parent)
        blocked = policy(final_parent / target.final_path.name)
        if blocked:
            raise UnsafeTargetError(errno.EPERM, blocked, target.final_path)
        _require_current(target, parent)
        descriptor = os.open(
            temporary,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent,
        )
        _write(descriptor, payload)
        _require_current(target, parent)
        expected = _descriptor_identity(target.descriptor)
        replacement = _descriptor_identity(descriptor)
        exchange_between(
            parent,
            temporary,
            target.final_path.name,
        )
        exchanged = True
        displaced = _path_identity(parent, temporary)
        if displaced != expected:
            _require_path_identity(
                parent,
                target.final_path.name,
                replacement,
            )
            _require_path_identity(parent, temporary, displaced)
            exchange_between(
                parent,
                temporary,
                target.final_path.name,
            )
            exchanged = False
            raise OSError(
                errno.ESTALE,
                "file changed during atomic edit",
            )
        retire_bound_path(
            final_parent / temporary,
            target.descriptor,
            expected,
        )
        published = True
        os.fsync(parent)
    finally:
        if descriptor >= 0:
            if not published and not exchanged:
                try:
                    retire_bound_path(
                        final_parent / temporary,
                        descriptor,
                        _descriptor_identity(descriptor),
                    )
                except OSError:
                    os.ftruncate(descriptor, 0)
                    os.fsync(descriptor)
            os.close(descriptor)
        os.close(parent)


def _replace_windows(
    target: OpenedTarget,
    payload: bytes,
    policy: PathPolicy,
) -> None:
    from .file_target_windows import (
        mark_delete,
        move_open_descriptor_no_replace,
        open_created,
        open_existing_deletable,
        replace_with_backup,
    )

    blocked = policy(target.final_path)
    if blocked:
        raise UnsafeTargetError(errno.EPERM, blocked, target.final_path)
    temporary = target.final_path.with_name(
        f".{target.final_path.name}.birkin-edit-{secrets.token_hex(8)}"
    )
    backup = target.final_path.with_name(
        f".{target.final_path.name}.birkin-edit-backup-{secrets.token_hex(8)}"
    )
    descriptor = open_created(temporary)
    backup_descriptor = -1
    replacement_identity: tuple[int, int] | None = None
    replaced = False
    try:
        _write(descriptor, payload)
        _require_current_path(target)
        expected = _descriptor_identity(target.descriptor)
        replacement_identity = _descriptor_identity(descriptor)
        os.close(descriptor)
        descriptor = -1
        close_target(target)
        replace_with_backup(target.final_path, temporary, backup)
        replaced = True
        backup_descriptor = open_existing_deletable(backup)
        if _descriptor_identity(backup_descriptor) != expected:
            failed_edit = target.final_path.with_name(
                f".{target.final_path.name}.birkin-edit-rejected-{secrets.token_hex(8)}"
            )
            edited_descriptor = open_existing_deletable(
                target.final_path,
            )
            try:
                if (
                    _descriptor_identity(edited_descriptor)
                    != replacement_identity
                ):
                    raise OSError(
                        errno.ESTALE,
                        "file changed during atomic edit restoration",
                    )
                move_open_descriptor_no_replace(
                    edited_descriptor,
                    failed_edit,
                )
                move_open_descriptor_no_replace(
                    backup_descriptor,
                    target.final_path,
                )
                mark_delete(edited_descriptor)
            finally:
                os.close(edited_descriptor)
            raise OSError(
                errno.ESTALE,
                "file changed during atomic edit",
            )
        mark_delete(backup_descriptor)
    finally:
        if backup_descriptor >= 0:
            os.close(backup_descriptor)
        if descriptor >= 0:
            if not replaced:
                mark_delete(descriptor)
            os.close(descriptor)
        elif not replaced and replacement_identity is not None:
            _retire_windows_path(temporary, replacement_identity)


def _retire_windows_path(
    path: Path,
    expected_identity: tuple[int, int],
) -> None:
    from .file_target_windows import (
        mark_delete,
        open_existing_deletable,
    )

    try:
        descriptor = open_existing_deletable(path)
    except FileNotFoundError:
        return
    try:
        if _descriptor_identity(descriptor) == expected_identity:
            mark_delete(descriptor)
    finally:
        os.close(descriptor)


def _require_current(target: OpenedTarget, parent: int) -> None:
    _require_path_identity(
        parent,
        target.final_path.name,
        _descriptor_identity(target.descriptor),
    )


def _require_path_identity(
    parent: int,
    name: str,
    expected: tuple[int, int],
) -> None:
    if _path_identity(parent, name) != expected:
        raise OSError(errno.ESTALE, "file changed before atomic edit")


def _path_identity(parent: int, name: str) -> tuple[int, int]:
    current = os.stat(name, dir_fd=parent, follow_symlinks=False)
    return current.st_dev, current.st_ino


def _descriptor_identity(descriptor: int) -> tuple[int, int]:
    current = os.fstat(descriptor)
    return current.st_dev, current.st_ino


def _require_current_path(target: OpenedTarget) -> None:
    current = target.final_path.stat(follow_symlinks=False)
    expected = os.fstat(target.descriptor)
    if (
        current.st_dev,
        current.st_ino,
    ) != (
        expected.st_dev,
        expected.st_ino,
    ):
        raise OSError(errno.ESTALE, "file changed before atomic edit")


def _write(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    written = 0
    while written < len(view):
        count = os.write(descriptor, view[written:])
        if count <= 0:
            raise OSError(errno.EIO, "atomic edit made no progress")
        written += count
    os.fsync(descriptor)
