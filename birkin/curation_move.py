"""Descriptor-relative POSIX move state machine for curation."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from .curation_contract import CurationResidueError
from .skills.bundle_publish import _rename_noreplace
from .skills.manager import (
    _close_preserving_active_error,
    _open_descendant_directory,
)


def move_anchored(
    root_fd: int,
    source_relative: Path,
    destination_relative: Path,
    source: int,
) -> None:
    source_parent = -1
    destination_parent = -1
    destination = -1
    moved = False
    try:
        source_parent = _open_descendant_directory(
            root_fd,
            source_relative.parent,
        )
        destination_parent = _open_descendant_directory(
            root_fd,
            destination_relative.parent,
            create=True,
        )
        opened = os.fstat(source)
        named = os.stat(
            source_relative.name,
            dir_fd=source_parent,
            follow_symlinks=False,
        )
        if (named.st_dev, named.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            raise OSError("curation move identity changed")
        try:
            _rename_noreplace(
                source_relative.name,
                destination_relative.name,
                source_fd=source_parent,
                destination_fd=destination_parent,
            )
            moved = True
        except OSError as rename_error:
            destination = _resolve_ambiguous_rename(
                source_relative,
                destination_relative,
                source_parent,
                destination_parent,
                opened,
                rename_error,
            )
            moved = True
        if destination < 0:
            destination = os.open(
                destination_relative.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=destination_parent,
            )
        published = os.fstat(destination)
        if (
            not stat.S_ISREG(published.st_mode)
            or published.st_nlink != 1
            or (published.st_dev, published.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            )
        ):
            raise CurationResidueError(
                "curation move identity changed after publication"
            )
    except CurationResidueError:
        raise
    except OSError as error:
        _rollback_verified_move(
            moved,
            destination,
            source,
            source_relative,
            destination_relative,
            source_parent,
            destination_parent,
            error,
        )
        raise
    finally:
        active_error = sys.exc_info()[1]
        close_error: OSError | None = None
        for descriptor in (
            destination,
            destination_parent,
            source_parent,
        ):
            if descriptor < 0:
                continue
            try:
                _close_preserving_active_error(descriptor)
            except OSError as error:
                close_error = close_error or error
        if active_error is None and close_error is not None:
            if moved:
                raise CurationResidueError(
                    "curation move close failed after publication"
                ) from close_error
            raise close_error


def _resolve_ambiguous_rename(
    source_relative: Path,
    destination_relative: Path,
    source_parent: int,
    destination_parent: int,
    opened: os.stat_result,
    rename_error: OSError,
) -> int:
    try:
        still_named = os.stat(
            source_relative.name,
            dir_fd=source_parent,
            follow_symlinks=False,
        )
    except OSError:
        still_named = None
    if still_named is not None and (
        still_named.st_dev,
        still_named.st_ino,
    ) == (opened.st_dev, opened.st_ino):
        raise rename_error
    destination = -1
    try:
        destination = os.open(
            destination_relative.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=destination_parent,
        )
        published = os.fstat(destination)
    except OSError as verification_error:
        if destination >= 0:
            _close_preserving_active_error(destination)
        raise CurationResidueError(
            "curation move outcome is indeterminate"
        ) from verification_error
    if (published.st_dev, published.st_ino) != (
        opened.st_dev,
        opened.st_ino,
    ):
        residue = CurationResidueError(
            "curation move outcome is indeterminate"
        )
        try:
            raise residue from rename_error
        finally:
            _close_preserving_active_error(destination)
    return destination


def _rollback_verified_move(
    moved: bool,
    destination: int,
    source: int,
    source_relative: Path,
    destination_relative: Path,
    source_parent: int,
    destination_parent: int,
    error: OSError,
) -> None:
    if not moved:
        return
    if destination < 0:
        raise CurationResidueError(
            "curation move verification failed after publication"
        ) from error
    try:
        published = os.fstat(destination)
        opened = os.fstat(source)
    except OSError as verification_error:
        raise CurationResidueError(
            "curation move verification failed after publication"
        ) from verification_error
    if (published.st_dev, published.st_ino) != (
        opened.st_dev,
        opened.st_ino,
    ):
        raise CurationResidueError(
            "curation move identity changed after publication"
        ) from error
    try:
        _rename_noreplace(
            destination_relative.name,
            source_relative.name,
            source_fd=destination_parent,
            destination_fd=source_parent,
        )
    except OSError as rollback_error:
        raise CurationResidueError(
            "curation move rollback failed"
        ) from rollback_error
