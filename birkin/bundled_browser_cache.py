"""Private verified cache for browser runtimes on read-only volumes."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, Protocol, cast


class RuntimeCacheError(RuntimeError):
    """A read-only runtime could not be published safely."""


RuntimeVerifier = Callable[[Path], None]
_RUNTIME_LEASES: list[BinaryIO] = []


class _VolumeStatus(Protocol):
    f_flag: int


def select_browser_runtime(
    source: Path,
    *,
    architecture: str,
    sha256: str,
    verify: RuntimeVerifier,
) -> Path:
    """Return the source or an atomically published private copy."""
    if not _is_read_only(source):
        return source
    home_raw = os.environ.get("BIRKIN_HOME")
    if not home_raw:
        raise RuntimeCacheError
    home = Path(home_raw)
    if not home.is_absolute() or home.is_symlink():
        raise RuntimeCacheError
    parent = home / "browser-runtime-cache"
    if parent.is_symlink():
        raise RuntimeCacheError
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent.chmod(0o700)
    except OSError as error:
        raise RuntimeCacheError from error
    target = parent / f"{architecture}-{sha256}"
    lease = _acquire_shared_lease(parent, target.name)
    try:
        if target.is_symlink():
            raise RuntimeCacheError
        if target.exists():
            verify(target)
        else:
            _publish_runtime(
                source,
                target,
                lease,
                verify,
            )
        _RUNTIME_LEASES.append(lease)
        lease = None
        _prune_stale(parent, target, architecture)
        return target
    except RuntimeCacheError:
        raise
    except OSError as error:
        raise RuntimeCacheError from error
    finally:
        if lease is not None:
            lease.close()


def _publish_runtime(
    source: Path,
    target: Path,
    lease: BinaryIO,
    verify: RuntimeVerifier,
) -> None:
    import fcntl

    fcntl.flock(lease.fileno(), fcntl.LOCK_UN)
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX)
    if target.is_symlink():
        raise RuntimeCacheError
    if target.exists():
        verify(target)
        fcntl.flock(lease.fileno(), fcntl.LOCK_SH)
        return
    stage = target.parent / f".{target.name}.staging"
    if stage.is_symlink():
        raise RuntimeCacheError
    if stage.exists():
        shutil.rmtree(stage)
    try:
        _ = shutil.copytree(source, stage)
        stage.chmod(0o700)
        verify(stage)
        _ = stage.rename(target)
        fcntl.flock(lease.fileno(), fcntl.LOCK_SH)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _acquire_shared_lease(
    parent: Path,
    target_name: str,
) -> BinaryIO:
    import fcntl

    lease_path = parent / f".lease-{target_name}"
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lease_path, flags, 0o600)
    except OSError as error:
        raise RuntimeCacheError from error
    lease = os.fdopen(descriptor, "a+b", buffering=0)
    try:
        fcntl.flock(lease.fileno(), fcntl.LOCK_SH)
    except OSError as error:
        lease.close()
        raise RuntimeCacheError from error
    return lease


def _prune_stale(
    parent: Path,
    keep: Path,
    architecture: str,
) -> None:
    try:
        for entry in parent.iterdir():
            if entry == keep:
                continue
            target_name: str
            if entry.name.startswith(f"{architecture}-"):
                target_name = entry.name
            elif (
                entry.name.startswith(f".{architecture}-")
                and entry.name.endswith(".staging")
            ):
                target_name = entry.name[1:-len(".staging")]
            else:
                continue
            lease = _try_exclusive_lease(parent, target_name)
            if lease is None:
                continue
            try:
                if entry.is_symlink() or not entry.is_dir():
                    entry.unlink()
                else:
                    shutil.rmtree(entry)
            finally:
                lease.close()
    except OSError as error:
        raise RuntimeCacheError from error


def _try_exclusive_lease(
    parent: Path,
    target_name: str,
) -> BinaryIO | None:
    import fcntl

    lease_path = parent / f".lease-{target_name}"
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lease_path, flags, 0o600)
        lease = os.fdopen(descriptor, "a+b", buffering=0)
        try:
            fcntl.flock(
                lease.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            lease.close()
            return None
        return lease
    except OSError as error:
        raise RuntimeCacheError from error


def _is_read_only(root: Path) -> bool:
    statvfs_raw = getattr(os, "statvfs", None)
    read_only = getattr(os, "ST_RDONLY", None)
    if statvfs_raw is None or not isinstance(read_only, int):
        return False
    statvfs = cast(Callable[[Path], object], statvfs_raw)
    status = cast(_VolumeStatus, statvfs(root))
    return bool(status.f_flag & read_only)
