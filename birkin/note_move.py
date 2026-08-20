"""Identity-checked, no-replace note moves."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def move_note_noreplace(old: Path, new: Path) -> None:
    if os.name == "nt":
        os.rename(old, new)
        return

    from .skills.bundle_publish import _rename_noreplace

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    source_parent = os.open(old.parent, flags)
    destination_parent = os.open(new.parent, flags)
    source = -1
    try:
        source = os.open(
            old.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=source_parent,
        )
        source_status = os.fstat(source)
        _rename_noreplace(
            old.name,
            new.name,
            source_fd=source_parent,
            destination_fd=destination_parent,
        )
        moved_status = os.stat(
            new.name,
            dir_fd=destination_parent,
            follow_symlinks=False,
        )
        if (
            moved_status.st_dev,
            moved_status.st_ino,
        ) != (
            source_status.st_dev,
            source_status.st_ino,
        ):
            try:
                _rename_noreplace(
                    new.name,
                    old.name,
                    source_fd=destination_parent,
                    destination_fd=source_parent,
                )
            except OSError:
                pass
            raise OSError("note source identity changed")
    finally:
        active_error = sys.exc_info()[1]
        close_error: OSError | None = None
        for descriptor in (
            source,
            destination_parent,
            source_parent,
        ):
            if descriptor < 0:
                continue
            try:
                os.close(descriptor)
            except OSError as error:
                close_error = close_error or error
        if active_error is None and close_error is not None:
            raise close_error
