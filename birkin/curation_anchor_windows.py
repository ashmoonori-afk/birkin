"""Handle-pinned curation mutations for one Windows vault."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

from .curation_contract import CurationResidueError
from .curation_windows_io import (
    link_count,
    read_handle,
    write_handle,
)
from .memory import VaultMemory
from .skills.bundle_publish_windows_io import (
    DELETE,
    DIRECTORY_ATTRIBUTE,
    READ_ATTRIBUTES,
    REPARSE_ATTRIBUTE,
    checked_directory,
    close,
    information,
    open_handle,
    rename,
)
from .skills.manager import _windows_kernel32

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000


class WindowsAnchoredCuration:
    def __init__(
        self,
        root: Path,
        entries: dict[str, dict[str, Any]],
        memory: VaultMemory,
    ) -> None:
        self._root = root
        self._entries = {
            slug: dict(entry)
            for slug, entry in entries.items()
        }
        self._memory = memory
        self._kernel32 = _windows_kernel32()
        self._handles: dict[str, int] = {}
        try:
            for slug in self._entries:
                handle = open_handle(
                    self._kernel32,
                    root / self._relative(slug),
                    access=(
                        GENERIC_READ
                        | GENERIC_WRITE
                        | READ_ATTRIBUTES
                        | DELETE
                    ),
                    directory=False,
                )
                try:
                    self._validate(handle)
                except BaseException:
                    close(self._kernel32, handle)
                    raise
                self._handles[slug] = handle
        except BaseException:
            self.close()
            raise

    def _relative(self, slug: str) -> Path:
        entry = self._entries.get(slug)
        if entry is None:
            raise ValueError(f"no note with slug {slug!r}")
        return Path(str(entry["rel"]))

    def _validate(self, handle: int) -> None:
        attributes, _ = information(self._kernel32, handle)
        if (
            attributes & REPARSE_ATTRIBUTE
            or attributes & DIRECTORY_ATTRIBUTE
        ):
            raise OSError("curation note is not a regular file")
        if link_count(self._kernel32, handle) != 1:
            raise OSError("curation note has multiple hard links")

    def _read(self, handle: int) -> bytes:
        self._validate(handle)
        return read_handle(self._kernel32, handle)

    def _write(self, handle: int, payload: bytes) -> None:
        self._validate(handle)
        write_handle(self._kernel32, handle, payload)

    def read(self, slug: str) -> tuple[Path, str]:
        relative = self._relative(slug)
        payload = self._read(self._handles[slug])
        return (
            self._memory.vault / relative,
            payload.decode("utf-8", errors="replace"),
        )

    def write(self, slug: str, text: str) -> Path:
        handle = self._handles[slug]
        relative = self._relative(slug)
        previous = self._read(handle)
        source, _ = self._memory._record_source_payload(
            relative,
            previous,
        )
        payload = text.encode("utf-8")
        try:
            self._write(handle, payload)
            self._validate(handle)
        except OSError:
            try:
                write_handle(
                    self._kernel32,
                    handle,
                    previous,
                )
            except OSError as restore_error:
                raise CurationResidueError(
                    "Windows curation note restoration failed"
                ) from restore_error
            raise
        try:
            self._memory._register_record_source_relative(
                relative,
                source,
                digest=hashlib.sha256(payload).hexdigest(),
            )
        except OSError as provenance_error:
            raise CurationResidueError(
                "Windows curation provenance failed after write"
            ) from provenance_error
        return self._memory.vault / relative

    def move(self, slug: str, zone: str) -> Path:
        relative = self._relative(slug)
        destination_zone = "" if zone in ("", "inbox") else zone
        destination_relative = (
            Path(destination_zone) / relative.name
            if destination_zone
            else Path(relative.name)
        )
        if destination_relative == relative:
            return self._memory.vault / relative

        handle = self._handles[slug]
        payload = self._read(handle)
        source, digest = self._memory._record_source_payload(
            relative,
            payload,
        )
        destination_path = self._root / destination_relative.parent
        destination_path.mkdir(parents=True, exist_ok=True)
        source_parent = -1
        destination_parent = -1
        moved = False
        try:
            source_parent = checked_directory(
                self._kernel32,
                self._root / relative.parent,
                access=READ_ATTRIBUTES,
            )
            destination_parent = checked_directory(
                self._kernel32,
                destination_path,
                access=READ_ATTRIBUTES,
            )
            rename(
                self._kernel32,
                handle,
                destination_parent,
                destination_path,
                destination_relative.name,
            )
            moved = True
            self._memory._register_record_source_relative(
                destination_relative,
                source,
                digest=digest,
                previous_relative=relative,
            )
        except OSError:
            if moved:
                try:
                    rename(
                        self._kernel32,
                        handle,
                        source_parent,
                        self._root / relative.parent,
                        relative.name,
                    )
                except OSError as rollback_error:
                    raise CurationResidueError(
                        "Windows curation move rollback failed"
                    ) from rollback_error
            raise
        finally:
            active_error = sys.exc_info()[1]
            close_error: OSError | None = None
            for parent in (
                destination_parent,
                source_parent,
            ):
                if parent < 0:
                    continue
                try:
                    close(self._kernel32, parent)
                except OSError as error:
                    close_error = close_error or error
            if active_error is None and close_error is not None:
                if moved:
                    raise CurationResidueError(
                        "Windows curation parent close failed "
                        "after move"
                    ) from close_error
                raise close_error
        self._entries[slug]["rel"] = destination_relative.as_posix()
        self._entries[slug]["zone"] = destination_zone
        return self._memory.vault / destination_relative

    def close(self) -> None:
        active_error = sys.exc_info()[1]
        close_error: OSError | None = None
        for handle in reversed(tuple(self._handles.values())):
            try:
                close(self._kernel32, handle)
            except OSError as error:
                close_error = close_error or error
        self._handles.clear()
        if active_error is None and close_error is not None:
            raise close_error
