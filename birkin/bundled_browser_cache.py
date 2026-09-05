"""Private verified cache for browser runtimes on read-only volumes."""

from __future__ import annotations

import logging
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import BinaryIO, Protocol, cast


class RuntimeCacheError(RuntimeError):
    """A read-only runtime could not be published safely."""


RuntimeVerifier = Callable[[Path], None]
_RUNTIME_LEASES: dict[Path, BinaryIO] = {}
_RUNTIME_LEASES_LOCK = Lock()
_LOG = logging.getLogger(__name__)
_BACKUP_EXCLUSION_XATTR = b"com.apple.metadata:com_apple_backup_excludeItem"
_BACKUP_EXCLUSION_VALUE = bytes.fromhex(
    "62706c69737430305f1011636f6d2e6170706c652e6261636b7570640800000000000000010100000000000000010000000000000000000000000000001c"
)
_XATTR_NOFOLLOW = 0x0001


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
        _exclude_from_backups(parent)
    except OSError as error:
        raise RuntimeCacheError from error
    target = parent / f"{architecture}-{sha256}"
    publication = _acquire_publication_lock(parent, target.name)
    lease: BinaryIO | None = None
    try:
        if target.is_symlink():
            raise RuntimeCacheError
        if target.exists():
            verify(target)
        else:
            _publish_runtime(source, target, verify)
        lease = _acquire_shared_lease(parent, target.name)
        if _retain_runtime_lease(target, lease):
            lease = None
    except RuntimeCacheError:
        raise
    except OSError as error:
        raise RuntimeCacheError from error
    finally:
        publication.close()
        if lease is not None:
            lease.close()
    _prune_stale(parent, target, architecture)
    return target


def _exclude_from_backups(path: Path) -> None:
    if not _running_on_darwin():
        return
    try:
        _set_backup_exclusion_xattr(path)
    except OSError as error:
        error_number = error.errno if error.errno is not None else 0
        _LOG.warning(
            "Browser runtime cache backup exclusion unavailable (errno %d).",
            error_number,
        )


def _running_on_darwin() -> bool:
    return sys.platform == "darwin"


def _set_backup_exclusion_xattr(path: Path) -> None:
    import ctypes

    setxattr = ctypes.CDLL(None, use_errno=True).setxattr
    setxattr.argtypes = (
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    )
    setxattr.restype = ctypes.c_int
    value = ctypes.create_string_buffer(_BACKUP_EXCLUSION_VALUE)
    result = cast(
        int,
        setxattr(
            os.fsencode(path),
            _BACKUP_EXCLUSION_XATTR,
            ctypes.byref(value),
            len(_BACKUP_EXCLUSION_VALUE),
            0,
            _XATTR_NOFOLLOW,
        ),
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def _retain_runtime_lease(
    target: Path,
    lease: BinaryIO,
) -> bool:
    with _RUNTIME_LEASES_LOCK:
        if target in _RUNTIME_LEASES:
            return False
        _RUNTIME_LEASES[target] = lease
        return True


def _publish_runtime(
    source: Path,
    target: Path,
    verify: RuntimeVerifier,
) -> None:
    if target.is_symlink():
        raise RuntimeCacheError
    if target.exists():
        verify(target)
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
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _acquire_publication_lock(
    parent: Path,
    target_name: str,
) -> BinaryIO:
    import fcntl

    publication = _open_lock(parent / f".publish-{target_name}")
    try:
        fcntl.flock(publication.fileno(), fcntl.LOCK_EX)
    except OSError as error:
        publication.close()
        raise RuntimeCacheError from error
    return publication


def _acquire_shared_lease(
    parent: Path,
    target_name: str,
) -> BinaryIO:
    import fcntl

    lease = _open_lock(parent / f".lease-{target_name}")
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
            publication = _try_exclusive_lock(
                parent / f".publish-{target_name}"
            )
            if publication is None:
                continue
            lease = _try_exclusive_lease(parent, target_name)
            if lease is None:
                publication.close()
                continue
            try:
                if entry.is_symlink() or not entry.is_dir():
                    entry.unlink()
                else:
                    shutil.rmtree(entry)
            finally:
                lease.close()
                publication.close()
    except OSError as error:
        raise RuntimeCacheError from error


def _try_exclusive_lease(
    parent: Path,
    target_name: str,
) -> BinaryIO | None:
    return _try_exclusive_lock(parent / f".lease-{target_name}")


def _try_exclusive_lock(path: Path) -> BinaryIO | None:
    import fcntl

    lease = _open_lock(path)
    try:
        fcntl.flock(
            lease.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
    except BlockingIOError:
        lease.close()
        return None
    return lease


def _open_lock(path: Path) -> BinaryIO:
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        return os.fdopen(descriptor, "a+b", buffering=0)
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
