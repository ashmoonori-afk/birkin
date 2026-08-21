"""Canonical copy-in authority for native file imports."""

from __future__ import annotations

import hashlib
import os
import stat
import threading
import uuid
from pathlib import Path
from typing import Final, final

from birkin.workspace.contracts import JsonValue, ProtocolError
from birkin.workspace.service import CommandHandler


MAX_IMPORT_BYTES: Final = 64 * 1024 * 1024
MAX_JAIL_BYTES: Final = 512 * 1024 * 1024
_COPY_CHUNK_BYTES: Final = 1024 * 1024
_IMPORT_PREFIX: Final = "import-"
_IMPORT_ID_HEX_LENGTH: Final = 32


@final
class JailedImportAuthority:
    """Copy a dropped regular file into a private workspace jail.

    External paths are accepted only as copy sources. Neither the source path nor
    a caller-selected destination crosses the canonical result boundary.
    """

    def __init__(self, jail: Path) -> None:
        self._jail = jail
        self._jail.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._jail, 0o700)
        self._quota_lock = threading.Lock()
        self._reserved_bytes = 0

    @property
    def jail(self) -> Path:
        return self._jail

    def handlers(self) -> dict[str, CommandHandler]:
        return {"file.import": self.import_file}

    def _reserve(self, byte_count: int) -> None:
        with self._quota_lock:
            owned_bytes = 0
            for entry in os.scandir(self._jail):
                identifier = entry.name[
                    len(_IMPORT_PREFIX):len(_IMPORT_PREFIX) + _IMPORT_ID_HEX_LENGTH
                ]
                suffix = entry.name[len(_IMPORT_PREFIX) + _IMPORT_ID_HEX_LENGTH:]
                owned_name = (
                    entry.name.startswith(_IMPORT_PREFIX)
                    and len(identifier) == _IMPORT_ID_HEX_LENGTH
                    and all(character in "0123456789abcdef" for character in identifier)
                    and (not suffix or suffix.startswith("."))
                    and len(suffix) <= 32
                )
                entry_stat = entry.stat(follow_symlinks=False)
                if owned_name and stat.S_ISREG(entry_stat.st_mode):
                    owned_bytes += entry_stat.st_size
            if owned_bytes + self._reserved_bytes + byte_count > MAX_JAIL_BYTES:
                raise ProtocolError("import jail exceeds aggregate byte limit")
            self._reserved_bytes += byte_count

    def import_file(self, payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if set(payload) != {"source_path"}:
            raise ProtocolError(
                "file.import accepts only the canonical source_path copy intent"
            )
        raw_source = payload["source_path"]
        if not isinstance(raw_source, str) or not raw_source:
            raise ProtocolError("source_path must identify a regular file")
        source = Path(raw_source)
        display_name = source.name
        if display_name in {"", ".", ".."}:
            raise ProtocolError("source_path must identify a regular file")

        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            source_fd = os.open(source, flags)
        except OSError as exc:
            raise ProtocolError("source_path must identify a regular file") from exc

        import_id = f"import-{uuid.uuid4().hex}"
        suffix = Path(display_name).suffix[:32]
        jail_name = f"{import_id}{suffix}"
        destination = self._jail / jail_name
        partial_destination = self._jail / f".partial-{uuid.uuid4().hex}"
        digest = hashlib.sha256()
        byte_count = 0
        destination_created = False
        copy_complete = False
        reservation = 0
        reservation_active = False
        try:
            source_stat = os.fstat(source_fd)
            if not stat.S_ISREG(source_stat.st_mode):
                raise ProtocolError("source_path must identify a regular file")
            if source_stat.st_size > MAX_IMPORT_BYTES:
                raise ProtocolError("source file exceeds byte limit")
            reservation = source_stat.st_size
            self._reserve(reservation)
            reservation_active = True
            destination_fd = os.open(
                partial_destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            destination_created = True
            try:
                while True:
                    file_remaining = MAX_IMPORT_BYTES - byte_count
                    reservation_remaining = reservation - byte_count
                    chunk = os.read(
                        source_fd,
                        min(
                            _COPY_CHUNK_BYTES,
                            file_remaining + 1,
                            reservation_remaining + 1,
                        ),
                    )
                    if not chunk:
                        break
                    if len(chunk) > file_remaining:
                        raise ProtocolError("source file exceeds byte limit")
                    if len(chunk) > reservation_remaining:
                        raise ProtocolError("source file changed during import")
                    digest.update(chunk)
                    byte_count += len(chunk)
                    view = memoryview(chunk)
                    while view:
                        written = os.write(destination_fd, view)
                        view = view[written:]
                os.fsync(destination_fd)
            finally:
                os.close(destination_fd)
            with self._quota_lock:
                os.replace(partial_destination, destination)
                self._reserved_bytes -= reservation
                reservation_active = False
            copy_complete = True
        finally:
            try:
                if destination_created and not copy_complete:
                    partial_destination.unlink(missing_ok=True)
            finally:
                try:
                    if reservation_active:
                        with self._quota_lock:
                            self._reserved_bytes -= reservation
                finally:
                    os.close(source_fd)

        sha256 = digest.hexdigest()
        reference: dict[str, JsonValue] = {
            "kind": "workspace_import",
            "import_id": import_id,
            "display_name": display_name,
            "jail_name": jail_name,
            "sha256": sha256,
            "byte_count": byte_count,
        }
        receipt: dict[str, JsonValue] = {
            "operation": "file.import",
            "import_id": import_id,
            "sha256": sha256,
            "byte_count": byte_count,
            "copied": True,
        }
        return {"reference": reference, "receipt": receipt}
