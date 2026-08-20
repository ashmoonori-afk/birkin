"""Descriptor-relative curation mutations for one pinned POSIX vault."""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from pathlib import Path
from typing import Any

from .curation_contract import CurationResidueError
from .memory import VaultMemory
from .skills.bundle_publish import _rename_noreplace
from .skills.manager import (
    _close_preserving_active_error,
    _open_descendant_directory,
    _write_all,
)

class AnchoredCuration:
    def __init__(
        self,
        root_fd: int,
        entries: dict[str, dict[str, Any]],
        memory: VaultMemory,
    ) -> None:
        self._root_fd = root_fd
        self._entries = {
            slug: dict(entry) for slug, entry in entries.items()
        }
        self._memory = memory
        self._identities: dict[str, tuple[int, int]] = {}
        for slug in self._entries:
            descriptor = self._open_note(slug, os.O_RDONLY)
            try:
                status = os.fstat(descriptor)
                self._identities[slug] = (
                    status.st_dev,
                    status.st_ino,
                )
            finally:
                os.close(descriptor)

    def _relative(self, slug: str) -> Path:
        entry = self._entries.get(slug)
        if entry is None:
            raise ValueError(f"no note with slug {slug!r}")
        return Path(str(entry["rel"]))

    def _open_note(self, slug: str, flags: int) -> int:
        relative = self._relative(slug)
        parent = _open_descendant_directory(
            self._root_fd,
            relative.parent,
        )
        try:
            descriptor = os.open(
                relative.name,
                flags | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent,
            )
        finally:
            os.close(parent)
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            os.close(descriptor)
            raise OSError("curation note is not a regular file")
        if status.st_nlink != 1:
            os.close(descriptor)
            raise OSError("curation note has multiple hard links")
        expected = self._identities.get(slug)
        if expected is not None and (
            status.st_dev,
            status.st_ino,
        ) != expected:
            os.close(descriptor)
            raise OSError("curation note identity changed")
        return descriptor

    def read(self, slug: str) -> tuple[Path, str]:
        descriptor = self._open_note(slug, os.O_RDONLY)
        try:
            payload = self._read_descriptor(descriptor)
        finally:
            os.close(descriptor)
        return (
            self._memory.vault / self._relative(slug),
            payload.decode("utf-8", errors="replace"),
        )

    @staticmethod
    def _read_descriptor(descriptor: int) -> bytes:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 64 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)

    def write(self, slug: str, text: str) -> Path:
        descriptor = self._open_note(slug, os.O_RDWR)
        relative = self._relative(slug)
        try:
            previous = self._read_descriptor(descriptor)
            source, _ = self._memory._record_source_payload(
                relative,
                previous,
            )
            payload = text.encode("utf-8")
            os.ftruncate(descriptor, 0)
            os.lseek(descriptor, 0, os.SEEK_SET)
            _write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._memory._register_record_source_relative(
            relative,
            source,
            digest=hashlib.sha256(payload).hexdigest(),
        )
        return self._memory.vault / relative

    def move(self, slug: str, zone: str) -> Path:
        relative = self._relative(slug)
        destination_zone = "" if zone in ("", "inbox") else zone
        destination_relative = (Path(destination_zone) / relative.name
                                if destination_zone else Path(relative.name))
        if destination_relative == relative:
            return self._memory.vault / relative

        source = -1
        source_parent = -1
        destination_parent = -1
        destination = -1
        moved = False
        try:
            source = self._open_note(slug, os.O_RDONLY)
            payload = self._read_descriptor(source)
            record_source, digest = self._memory._record_source_payload(
                relative,
                payload,
            )
            source_parent = _open_descendant_directory(
                self._root_fd,
                relative.parent,
            )
            destination_parent = _open_descendant_directory(
                self._root_fd,
                destination_relative.parent,
                create=True,
            )
            opened = os.fstat(source)
            named = os.stat(
                relative.name,
                dir_fd=source_parent,
                follow_symlinks=False,
            )
            if (named.st_dev, named.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ):
                raise OSError("curation move identity changed")
            _rename_noreplace(
                relative.name,
                destination_relative.name,
                source_fd=source_parent,
                destination_fd=destination_parent,
            )
            moved = True
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
            if moved and destination < 0:
                raise CurationResidueError(
                    "curation move verification failed after publication"
                ) from error
            if moved:
                try:
                    published = os.fstat(destination)
                    opened = os.fstat(source)
                except OSError as verification_error:
                    raise CurationResidueError(
                        "curation move verification failed after "
                        "publication"
                    ) from verification_error
                if (published.st_dev, published.st_ino) == (
                    opened.st_dev,
                    opened.st_ino,
                ):
                    try:
                        _rename_noreplace(
                            destination_relative.name,
                            relative.name,
                            source_fd=destination_parent,
                            destination_fd=source_parent,
                        )
                    except OSError as rollback_error:
                        raise CurationResidueError(
                            "curation move rollback failed"
                        ) from rollback_error
                else:
                    raise CurationResidueError(
                        "curation move identity changed after "
                        "publication"
                    ) from error
            raise
        finally:
            active_error = sys.exc_info()[1]
            close_error: OSError | None = None
            for descriptor in (
                destination,
                source,
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
                raise close_error

        self._entries[slug]["rel"] = (
            destination_relative.as_posix()
        )
        self._entries[slug]["zone"] = destination_zone
        destination_path = self._memory.vault / destination_relative
        self._memory._register_record_source_relative(
            destination_relative,
            record_source,
            digest=digest,
            previous_relative=relative,
        )
        return destination_path
