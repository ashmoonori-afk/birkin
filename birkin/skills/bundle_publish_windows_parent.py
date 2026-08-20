"""Locked Windows parent traversal for bundle publication."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import manager as _manager
from .bundle_publish_windows_io import (
    FILE_TRAVERSE,
    READ_ATTRIBUTES,
    SHARE_READ_WRITE,
    checked_directory,
    close,
)
from .bundle_publish_windows_native import (
    create_directory_handle,
)


def _missing(error: OSError) -> bool:
    return (
        getattr(error, "winerror", None)
        or getattr(error, "errno", None)
    ) in (2, 3)


@contextmanager
def locked_parent(
    target_root: Path,
    relative_parent: Path,
) -> Iterator[tuple[Path, int, Any]]:
    kernel32 = _manager._windows_kernel32()
    handles: list[int] = []
    current = Path(target_root.anchor)
    try:
        handles.append(checked_directory(
            kernel32,
            current,
            access=READ_ATTRIBUTES | FILE_TRAVERSE,
        ))
        for part in (
            *target_root.parts[1:],
            *relative_parent.parts,
        ):
            child = current / part
            try:
                handle = checked_directory(
                    kernel32,
                    child,
                    access=READ_ATTRIBUTES | FILE_TRAVERSE,
                )
            except OSError as error:
                if not _missing(error):
                    raise
                handle = create_directory_handle(
                    handles[-1],
                    current,
                    part,
                    access=READ_ATTRIBUTES | FILE_TRAVERSE,
                    share=SHARE_READ_WRITE,
                )
            handles.append(handle)
            current = child
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
