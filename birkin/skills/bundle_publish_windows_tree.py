"""Exact Windows bundle-tree handle ownership and cleanup."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bundle_publish_windows_io import (
    DELETE,
    DIRECTORY_ATTRIBUTE,
    READ_ATTRIBUTES,
    REPARSE_ATTRIBUTE,
    SHARE_READ_WRITE_DELETE,
    close,
    information,
    mark_delete,
    open_handle,
)


@dataclass
class TreeHandles:
    files: list[int] = field(default_factory=list)
    directories: list[int] = field(default_factory=list)


def lock_existing_tree(
    kernel32: Any,
    root: Path,
) -> TreeHandles:
    handles = TreeHandles()
    try:
        _lock_children(kernel32, root, handles)
    except BaseException:
        close_tree(kernel32, handles)
        raise
    return handles


def _lock_children(
    kernel32: Any,
    root: Path,
    handles: TreeHandles,
) -> None:
    for entry in os.scandir(root):
        expected_identity = entry.inode()
        path = Path(entry.path)
        is_directory = entry.is_dir(follow_symlinks=False)
        # Windows refuses to rename a directory while anything inside it is
        # held open without delete sharing, so the locks that guard the
        # existing tree have to allow it or the publish rename cannot run.
        handle = open_handle(
            kernel32,
            path,
            access=READ_ATTRIBUTES | DELETE,
            share=SHARE_READ_WRITE_DELETE,
            directory=is_directory,
        )
        try:
            attributes, identity = information(kernel32, handle)
            if identity != expected_identity:
                raise OSError("bundle tree identity changed")
            if (
                is_directory
                and attributes & DIRECTORY_ATTRIBUTE
                and not attributes & REPARSE_ATTRIBUTE
            ):
                handles.directories.append(handle)
                handle = -1
                _lock_children(
                    kernel32,
                    path,
                    handles,
                )
            else:
                handles.files.append(handle)
                handle = -1
        finally:
            if handle >= 0:
                close(kernel32, handle)


def close_tree(
    kernel32: Any,
    handles: TreeHandles,
) -> None:
    active_error = sys.exc_info()[1]
    close_error: OSError | None = None
    for handle in (
        *reversed(handles.files),
        *reversed(handles.directories),
    ):
        try:
            close(kernel32, handle)
        except OSError as error:
            close_error = close_error or error
    handles.files.clear()
    handles.directories.clear()
    if active_error is None and close_error is not None:
        raise close_error


def delete_tree_handles(
    kernel32: Any,
    handles: TreeHandles,
) -> None:
    cleanup_error: OSError | None = None
    for collection in (
        handles.files,
        reversed(handles.directories),
    ):
        for handle in tuple(collection):
            try:
                mark_delete(kernel32, handle)
            except OSError as error:
                cleanup_error = cleanup_error or error
            try:
                close(kernel32, handle)
            except OSError as error:
                cleanup_error = cleanup_error or error
    handles.files.clear()
    handles.directories.clear()
    if cleanup_error is not None:
        raise cleanup_error
