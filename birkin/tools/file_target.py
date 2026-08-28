"""Descriptor-bound generic file-tool I/O."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import stat
import sys


class UnsafeTargetError(OSError):
    """An opened object violates a file-tool trust boundary."""

@dataclass
class OpenedTarget:
    descriptor: int
    final_path: Path

PathPolicy = Callable[[Path], str]


def open_existing(
    path: Path,
    *,
    writable: bool,
    policy: PathPolicy,
) -> OpenedTarget:
    candidate = Path(os.path.realpath(path))
    flags = (
        (os.O_RDWR if writable else os.O_RDONLY)
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    if os.name == "nt":
        from .file_target_windows import open_existing as open_windows

        descriptor = open_windows(candidate, writable=writable)
    else:
        descriptor = os.open(candidate, flags)
    try:
        target = _target(descriptor)
        _authorize(target, policy)
        return target
    except Exception:
        os.close(descriptor)
        raise


def open_for_write(path: Path, policy: PathPolicy) -> OpenedTarget:
    try:
        return open_existing(path, writable=True, policy=policy)
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = Path(os.path.realpath(path))
    if os.name == "nt":
        return _create_windows(candidate, policy)
    return _create_posix(candidate, policy)


def read_bytes(target: OpenedTarget) -> bytes:
    _ = os.lseek(target.descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(target.descriptor, 64 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def replace_bytes(target: OpenedTarget, payload: bytes) -> None:
    previous = read_bytes(target)
    try:
        _write_bytes(target.descriptor, payload)
        _require_regular(target.descriptor)
    except OSError:
        try:
            _write_bytes(target.descriptor, previous)
        except OSError:
            pass
        raise


def close_target(target: OpenedTarget) -> None:
    descriptor = target.descriptor
    if descriptor < 0:
        return
    target.descriptor = -1
    os.close(descriptor)


def _create_posix(candidate: Path, policy: PathPolicy) -> OpenedTarget:
    directory = os.open(
        candidate.parent,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    descriptor = -1
    try:
        parent = descriptor_final_path(directory)
        blocked = policy(parent / candidate.name)
        if blocked:
            raise UnsafeTargetError(errno.EPERM, blocked, candidate)
        descriptor = os.open(
            candidate.name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory,
        )
        target = _target(descriptor)
        try:
            _authorize(target, policy)
        except Exception:
            from ..office.export_quarantine_retire import retire_bound_path

            retire_bound_path(
                target.final_path,
                descriptor,
                (
                    os.fstat(descriptor).st_dev,
                    os.fstat(descriptor).st_ino,
                ),
            )
            raise
        return target
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    finally:
        os.close(directory)


def _create_windows(candidate: Path, policy: PathPolicy) -> OpenedTarget:
    from .file_target_windows import open_created

    descriptor = open_created(candidate)
    try:
        target = _target(descriptor)
        _authorize(target, policy)
        return target
    except Exception:
        _mark_delete_windows(descriptor)
        os.close(descriptor)
        raise


def _target(descriptor: int) -> OpenedTarget:
    _require_regular(descriptor)
    return OpenedTarget(
        descriptor=descriptor,
        final_path=descriptor_final_path(descriptor),
    )


def _authorize(target: OpenedTarget, policy: PathPolicy) -> None:
    blocked = policy(target.final_path)
    if blocked:
        raise UnsafeTargetError(
            errno.EPERM,
            blocked,
            target.final_path,
        )


def _require_regular(descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise UnsafeTargetError(
            errno.EPERM,
            "unsafe file target",
        )


def _write_bytes(descriptor: int, payload: bytes) -> None:
    _ = os.lseek(descriptor, 0, os.SEEK_SET)
    os.ftruncate(descriptor, 0)
    view = memoryview(payload)
    written = 0
    while written < len(view):
        count = os.write(descriptor, view[written:])
        if count <= 0:
            raise OSError(errno.EIO, "file write made no progress")
        written += count
    os.fsync(descriptor)


def descriptor_final_path(descriptor: int) -> Path:
    if os.name == "nt":
        from .file_target_windows import final_path

        return final_path(descriptor)
    if sys.platform == "darwin":
        import fcntl

        raw = fcntl.fcntl(descriptor, 50, b"\0" * 1024)
        return Path(raw.split(b"\0", 1)[0].decode())
    if sys.platform.startswith("linux"):
        return Path(os.readlink(f"/proc/self/fd/{descriptor}"))
    raise OSError(errno.ENOTSUP, "descriptor final paths are unavailable")


def _mark_delete_windows(descriptor: int) -> None:
    from .file_target_windows import mark_delete

    mark_delete(descriptor)
