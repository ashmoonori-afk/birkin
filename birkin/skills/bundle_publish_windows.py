"""Handle-relative Windows publication for complete skill bundles."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .bundle_publish import BundleSnapshot
from .bundle_publish_windows_io import (
    DELETE,
    FILE_TRAVERSE,
    READ_ATTRIBUTES,
    SHARE_READ_WRITE_DELETE,
    checked_directory,
    close,
    mark_delete,
    open_handle,
    rename,
)
from .bundle_publish_windows_file import populate, verify_populated
from .bundle_publish_windows_native import create_directory_handle
from .bundle_publish_windows_parent import locked_parent, missing
from .bundle_publish_windows_tree import (
    TreeHandles, close_tree, delete_tree_handles, lock_existing_tree,
)
from .manager import PublicationCleanupError


def publish_windows(
    snapshot: BundleSnapshot, target: Path,
    target_root: Path, replace: bool) -> bool:
    relative = target.relative_to(target_root)
    with locked_parent(
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
            if not missing(error):
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
        candidate_tree = TreeHandles()
        previous_tree = TreeHandles()
        candidate = operation / "candidate"
        try:
            operation_handle = create_directory_handle(
                parent_handle,
                parent,
                operation.name,
                access=READ_ATTRIBUTES | DELETE,
                share=0x00000001 | 0x00000002,
            )
            operation_created = True
            operation_parent_handle = checked_directory(
                kernel32,
                operation,
                access=READ_ATTRIBUTES | FILE_TRAVERSE,
                share=SHARE_READ_WRITE_DELETE,
            )
            candidate_handle = create_directory_handle(
                operation_parent_handle,
                operation,
                candidate.name,
                access=READ_ATTRIBUTES | DELETE,
                share=0x00000001 | 0x00000002,
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
            populate(
                kernel32,
                candidate,
                candidate_handle,
                snapshot,
                candidate_tree,
            )
            verify_populated(candidate, snapshot)
            # Windows fails a directory rename outright while that directory
            # still contains open files ([MS-FSA] FileRenameInformation), so
            # the staged handles are released once the tree has been verified
            # against the snapshot. The same rule applies to the bundle being
            # replaced, which is why its tree is locked only after it has been
            # moved aside rather than before.
            close_tree(kernel32, candidate_tree)
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
                    previous_tree = lock_existing_tree(
                        kernel32,
                        operation / "previous",
                    )
                    delete_tree_handles(
                        kernel32,
                        previous_tree,
                    )
                    mark_delete(kernel32, previous_handle)
                    close(kernel32, previous_handle)
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
                    delete_tree_handles(
                        kernel32,
                        candidate_tree,
                    )
                    # A candidate that still holds entries refuses to be
                    # marked, which is what preserves an untracked file for
                    # inspection instead of deleting it with the bundle.
                    mark_delete(kernel32, candidate_handle)
                    close(kernel32, candidate_handle)
                    candidate_handle = -1
                except OSError as error:
                    preserve_operation = True
                    cleanup_error = cleanup_error or error
                    try:
                        close(kernel32, candidate_handle)
                    except OSError as close_error:
                        cleanup_error = (
                            cleanup_error or close_error
                        )
                    candidate_handle = -1
            elif candidate_handle >= 0:
                try:
                    close_tree(kernel32, candidate_tree)
                except OSError as error:
                    cleanup_error = cleanup_error or error
                try:
                    close(kernel32, candidate_handle)
                except OSError as error:
                    cleanup_error = cleanup_error or error
                candidate_handle = -1
            if (
                previous_tree.files
                or previous_tree.directories
            ):
                try:
                    close_tree(kernel32, previous_tree)
                except OSError as error:
                    cleanup_error = cleanup_error or error
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
