"""Private on-disk bootstrap record I/O for loopback authentication."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast, final

from birkin.native.private_storage import (
    harden_private_directory,
    harden_private_file,
)
from birkin.native.protocol import NativeProtocolError


@final
@dataclass(frozen=True, slots=True)
class BootstrapRecord:
    secret: str
    expires_at: datetime


def prepare_private_root(root: Path) -> None:
    harden_private_directory(root)


def new_record(now: datetime, ttl: timedelta) -> BootstrapRecord:
    return BootstrapRecord(
        secret=secrets.token_urlsafe(32),
        expires_at=now + ttl,
    )


def read_record(path: Path) -> BootstrapRecord:
    try:
        raw = cast(object, json.loads(path.read_text("utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise NativeProtocolError(
            "E_BOOTSTRAP_INVALID",
            "loopback bootstrap record is unavailable",
        ) from exc
    if not isinstance(raw, dict):
        raise NativeProtocolError(
            "E_BOOTSTRAP_INVALID",
            "loopback bootstrap record is malformed",
        )
    mapping = cast(dict[object, object], raw)
    secret = mapping.get("bootstrap_secret")
    expires_at = mapping.get("expires_at")
    if not isinstance(secret, str) or not isinstance(expires_at, str):
        raise NativeProtocolError(
            "E_BOOTSTRAP_INVALID",
            "loopback bootstrap record is malformed",
        )
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError as exc:
        raise NativeProtocolError(
            "E_BOOTSTRAP_INVALID",
            "loopback bootstrap record has an invalid expiry",
        ) from exc
    if expiry.tzinfo is None:
        raise NativeProtocolError(
            "E_BOOTSTRAP_INVALID",
            "loopback bootstrap expiry must be timezone-aware",
        )
    return BootstrapRecord(secret=secret, expires_at=expiry)


def write_record(
    path: Path,
    record: BootstrapRecord,
    *,
    metadata: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {
        "transport": "loopback",
        "bootstrap_secret": record.secret,
        "expires_at": record.expires_at.isoformat(),
    }
    if metadata is not None:
        payload.update(metadata)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        harden_private_file(temp_path)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        harden_private_file(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
