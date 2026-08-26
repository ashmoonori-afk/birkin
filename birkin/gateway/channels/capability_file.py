"""Owner-only gateway capability creation and durable publication."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from birkin.private_storage import (
    create_private_temp,
    open_private_file_for_read,
)

_IS_WINDOWS = os.name == "nt"


class CapabilityFileError(RuntimeError):
    """A gateway capability file violates its persistence contract."""


def _token_file() -> Path:
    from ...config import birkin_home

    return birkin_home() / "gateway_http_token"


def _read_token(path: Path) -> str:
    descriptor = open_private_file_for_read(path)
    try:
        payload = os.read(descriptor, 4097)
    finally:
        os.close(descriptor)
    token = payload.decode("utf-8").strip()
    if not token or len(payload) > 4096:
        raise CapabilityFileError(
            "gateway capability file is empty or malformed"
        )
    return token


def _fsync_directory(path: Path) -> None:
    """Persist publication on POSIX; Windows has no directory fsync API."""
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def load_or_create_token() -> tuple[str, Path]:
    """Read or atomically create the complete owner gateway capability."""
    path = _token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = _read_token(path)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        return existing, path
    token = secrets.token_urlsafe(32)
    if _IS_WINDOWS:
        descriptor, temporary_name = create_private_temp(
            path.parent,
            prefix=f".{path.name}.",
        )
        temporary = Path(temporary_name)
    else:
        temporary = path.with_name(
            f".{path.name}.{secrets.token_hex(16)}.tmp"
        )
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(temporary, flags, 0o600)
    try:
        try:
            payload = f"{token}\n".encode("utf-8")
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, path)
            temporary.unlink()
            _fsync_directory(path.parent)
        except FileExistsError:
            return _read_token(path), path
        return token, path
    finally:
        temporary.unlink(missing_ok=True)
