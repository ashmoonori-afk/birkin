"""Private verified cache for browser runtimes on read-only volumes."""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast


class RuntimeCacheError(RuntimeError):
    """A read-only runtime could not be published safely."""


RuntimeVerifier = Callable[[Path], None]


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
    if target.is_symlink():
        raise RuntimeCacheError
    if target.exists():
        verify(target)
        _prune_stale(parent, target, architecture)
        return target
    stage = Path(tempfile.mkdtemp(prefix=".runtime-", dir=parent))
    try:
        copied = stage / "runtime"
        _ = shutil.copytree(source, copied)
        copied.chmod(0o700)
        verify(copied)
        try:
            _ = copied.rename(target)
        except OSError as error:
            if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                raise
            if target.is_symlink():
                raise RuntimeCacheError from error
            verify(target)
        _prune_stale(parent, target, architecture)
        return target
    except RuntimeCacheError:
        raise
    except OSError as error:
        raise RuntimeCacheError from error
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _prune_stale(
    parent: Path,
    keep: Path,
    architecture: str,
) -> None:
    try:
        for entry in parent.iterdir():
            if entry == keep:
                continue
            if not (
                entry.name.startswith(".runtime-")
                or entry.name.startswith(f"{architecture}-")
            ):
                continue
            if entry.is_symlink() or not entry.is_dir():
                entry.unlink()
            else:
                shutil.rmtree(entry)
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
