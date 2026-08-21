"""Canonical copy-in authority for native file imports."""

from __future__ import annotations

import hashlib
import os
import stat
import uuid
from pathlib import Path
from typing import Final, final

from birkin.workspace.contracts import JsonValue, ProtocolError
from birkin.workspace.service import CommandHandler


MAX_IMPORT_BYTES: Final = 64 * 1024 * 1024
_COPY_CHUNK_BYTES: Final = 1024 * 1024


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

    @property
    def jail(self) -> Path:
        return self._jail

    def handlers(self) -> dict[str, CommandHandler]:
        return {"file.import": self.import_file}

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
        digest = hashlib.sha256()
        byte_count = 0
        destination_created = False
        copy_complete = False
        try:
            source_stat = os.fstat(source_fd)
            if not stat.S_ISREG(source_stat.st_mode):
                raise ProtocolError("source_path must identify a regular file")
            if source_stat.st_size > MAX_IMPORT_BYTES:
                raise ProtocolError("source file exceeds byte limit")
            destination_fd = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            destination_created = True
            try:
                while True:
                    remaining = MAX_IMPORT_BYTES - byte_count
                    chunk = os.read(
                        source_fd, min(_COPY_CHUNK_BYTES, remaining + 1)
                    )
                    if not chunk:
                        break
                    if len(chunk) > remaining:
                        raise ProtocolError("source file exceeds byte limit")
                    digest.update(chunk)
                    byte_count += len(chunk)
                    view = memoryview(chunk)
                    while view:
                        written = os.write(destination_fd, view)
                        view = view[written:]
                os.fsync(destination_fd)
                copy_complete = True
            finally:
                os.close(destination_fd)
        finally:
            try:
                if destination_created and not copy_complete:
                    destination.unlink(missing_ok=True)
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
