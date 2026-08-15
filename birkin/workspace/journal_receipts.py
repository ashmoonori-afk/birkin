"""Owner-private command receipt and live-owner sidecars."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import cast, final

from .records import CommandReceipt


@final
class ReceiptStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, command_id: str) -> Path:
        digest = hashlib.sha256(command_id.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def _owner_path(self, command_id: str) -> Path:
        digest = hashlib.sha256(command_id.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.owner"

    def read(self, command_id: str) -> CommandReceipt | None:
        path = self._path(command_id)
        if not path.is_file():
            return None
        raw = cast(object, json.loads(path.read_text(encoding="utf-8")))
        return CommandReceipt.from_json(raw)

    def write(self, receipt: CommandReceipt) -> None:
        path = self._path(receipt.command_id)
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        descriptor = os.open(
            temp,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            _ = handle.write(
                json.dumps(receipt.to_json(), ensure_ascii=False)
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)

    def owner_pid(self, command_id: str) -> int | None:
        path = self._owner_path(command_id)
        if not path.is_file():
            return None
        raw = cast(object, json.loads(path.read_text(encoding="utf-8")))
        if not isinstance(raw, dict):
            return None
        mapping = cast(dict[object, object], raw)
        pid = cast(object, mapping.get("pid"))
        return pid if isinstance(pid, int) and not isinstance(pid, bool) else None

    def write_owner(self, command_id: str) -> None:
        path = self._owner_path(command_id)
        descriptor = os.open(
            path,
            os.O_CREAT | os.O_TRUNC | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            _ = handle.write(json.dumps({"pid": os.getpid()}))
            handle.flush()
            os.fsync(handle.fileno())

    def clear_owner(self, command_id: str) -> None:
        self._owner_path(command_id).unlink(missing_ok=True)
