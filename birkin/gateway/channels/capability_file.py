"""Owner-only gateway capability creation and durable publication."""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path


class CapabilityFileError(RuntimeError):
    """A gateway capability file violates its persistence contract."""


def _token_file() -> Path:
    from ...config import birkin_home

    return birkin_home() / "gateway_http_token"


def _read_token(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise CapabilityFileError(
                "gateway capability path is not a regular file"
            )
        os.fchmod(descriptor, 0o600)
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


def _unlink_if_identity(path: Path, identity: tuple[int, int]) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        metadata = None
    if (
        metadata is not None
        and stat.S_ISREG(metadata.st_mode)
        and (metadata.st_dev, metadata.st_ino) == identity
    ):
        path.unlink()


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
    temporary = path.with_name(
        f".{path.name}.{secrets.token_hex(16)}.tmp"
    )
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(temporary, flags, 0o600)
        try:
            identity = os.fstat(descriptor)
            payload = f"{token}\n".encode("utf-8")
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, path)
            temporary.unlink()
            _fsync_directory(path.parent)
        except FileExistsError:
            return _read_token(path), path
        except OSError:
            _unlink_if_identity(
                path,
                (identity.st_dev, identity.st_ino),
            )
            raise
        return token, path
    finally:
        temporary.unlink(missing_ok=True)
