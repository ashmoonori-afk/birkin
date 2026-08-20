"""Handle-relative Windows publication for complete skill bundles."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .bundle_publish import BundleSnapshot
from .bundle_publish_windows_io import (
    DELETE,
    READ_ATTRIBUTES,
    REPARSE_ATTRIBUTE,
    SHARE_READ_WRITE_DELETE,
    checked_directory,
    close,
    delete_tree,
    information,
    mark_delete,
    open_handle,
    rename,
)
from .bundle_publish_windows_file import (
    create_directory,
    populate,
)
from . import manager as _manager
from .manager import PublicationCleanupError


@contextmanager
def _locked_parent(
    target_root: Path,
    relative_parent: Path,
) -> Iterator[tuple[Path, int, Any]]:
    kernel32 = _manager._windows_kernel32()
    handles: list[int] = []
    current = target_root
    try:
        for part in (None, *relative_parent.parts):
            if part is not None:
                current /= part
                if not current.exists():
                    create_directory(kernel32, current)
            handle = open_handle(
                kernel32,
                current,
                access=READ_ATTRIBUTES,
            )
            try:
                attributes, _ = information(kernel32, handle)
                if attributes & REPARSE_ATTRIBUTE:
                    raise OSError(
                        "skill mirror parent is a reparse point"
                    )
            except BaseException:
                close(kernel32, handle)
                raise
            handles.append(handle)
        yield current, handles[-1], kernel32
    finally:
        active_error = sys.exc_info()[1]
        close_error: OSError | None = None
        for handle in reversed(handles):
            try:
                close(kernel32, handle)
            except OSError as error:
                close_error = close_error or error
        if active_error is None and close_error is not None:
            raise close_error


def _missing(error: OSError) -> bool:
    return (
        getattr(error, "winerror", None)
        or getattr(error, "errno", None)
    ) in (2, 3)


def publish_windows(
    snapshot: BundleSnapshot,
    target: Path,
    target_root: Path,
    replace: bool,
) -> bool:
    relative = target.relative_to(target_root)
    with _locked_parent(
        target_root,
        relative.parent,
    ) as (parent, parent_handle, kernel32):
        destination = parent / relative.name
        try:
            previous_handle = open_handle(
                kernel32,
                destination,
                access=READ_ATTRIBUTES | DELETE,
            )
        except OSError as error:
            if not _missing(error):
                raise
            previous_handle = -1
        if previous_handle >= 0 and not replace:
            close(kernel32, previous_handle)
            return False

        operation = parent / f".birkin-sync-{os.urandom(12).hex()}"
        operation_handle = -1
        operation_parent_handle = -1
        candidate_handle = -1
        operation_created = False
        candidate = operation / "candidate"
        try:
            create_directory(kernel32, operation)
            operation_created = True
            operation_parent_handle = checked_directory(
                kernel32,
                operation,
                access=READ_ATTRIBUTES,
                share=SHARE_READ_WRITE_DELETE,
            )
            operation_handle = checked_directory(
                kernel32,
                operation,
                access=READ_ATTRIBUTES | DELETE,
            )
            create_directory(kernel32, candidate)
            candidate_handle = checked_directory(
                kernel32,
                candidate,
                access=READ_ATTRIBUTES | DELETE,
            )
        except OSError as setup_error:
            if candidate_handle >= 0:
                close(kernel32, candidate_handle)
            if operation_handle >= 0:
                close(kernel32, operation_handle)
            if operation_parent_handle >= 0:
                close(kernel32, operation_parent_handle)
            if previous_handle >= 0:
                close(kernel32, previous_handle)
            if operation_created:
                raise PublicationCleanupError(
                    relative.as_posix(),
                    snapshot.digest(),
                    getattr(setup_error, "winerror", None),
                ) from setup_error
            raise
        previous_moved = False
        published = False
        preserve_operation = False
        try:
            populate(kernel32, candidate, snapshot)
            if previous_handle >= 0:
                rename(
                    kernel32,
                    previous_handle,
                    operation_parent_handle,
                    operation,
                    "previous",
                )
                previous_moved = True
            try:
                rename(
                    kernel32,
                    candidate_handle,
                    parent_handle,
                    parent,
                    relative.name,
                )
                published = True
            except OSError:
                if previous_moved:
                    try:
                        rename(
                            kernel32,
                            previous_handle,
                            parent_handle,
                            parent,
                            relative.name,
                        )
                        previous_moved = False
                    except OSError as rollback_error:
                        preserve_operation = True
                        raise PublicationCleanupError(
                            relative.as_posix(),
                            snapshot.digest(),
                            getattr(
                                rollback_error,
                                "winerror",
                                None,
                            ),
                        ) from rollback_error
                raise
            if previous_moved:
                try:
                    delete_tree(
                        kernel32,
                        operation / "previous",
                        previous_handle,
                    )
                    previous_handle = -1
                    previous_moved = False
                except OSError as cleanup_error:
                    preserve_operation = True
                    raise PublicationCleanupError(
                        relative.as_posix(),
                        snapshot.digest(),
                        getattr(cleanup_error, "winerror", None),
                    ) from cleanup_error
        finally:
            active_error = sys.exc_info()[1]
            cleanup_error: OSError | None = None
            if not published and candidate_handle >= 0:
                try:
                    delete_tree(
                        kernel32,
                        candidate,
                        candidate_handle,
                    )
                    candidate_handle = -1
                except OSError as error:
                    preserve_operation = True
                    cleanup_error = cleanup_error or error
            elif candidate_handle >= 0:
                try:
                    close(kernel32, candidate_handle)
                except OSError as error:
                    cleanup_error = cleanup_error or error
                candidate_handle = -1
            if previous_handle >= 0:
                try:
                    close(kernel32, previous_handle)
                except OSError as error:
                    cleanup_error = cleanup_error or error
            if operation_parent_handle >= 0:
                try:
                    close(kernel32, operation_parent_handle)
                except OSError as error:
                    cleanup_error = cleanup_error or error
            if preserve_operation:
                try:
                    close(kernel32, operation_handle)
                except OSError as error:
                    cleanup_error = cleanup_error or error
            else:
                try:
                    mark_delete(kernel32, operation_handle)
                except OSError as error:
                    cleanup_error = cleanup_error or error
                try:
                    close(kernel32, operation_handle)
                except OSError as error:
                    cleanup_error = cleanup_error or error
            if (
                (preserve_operation or cleanup_error is not None)
                and not isinstance(
                    active_error,
                    PublicationCleanupError,
                )
            ):
                raise PublicationCleanupError(
                    relative.as_posix(),
                    snapshot.digest(),
                    getattr(cleanup_error, "winerror", None),
                ) from cleanup_error
        return True
