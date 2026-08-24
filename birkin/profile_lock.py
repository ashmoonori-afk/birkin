"""OS-level lock for role-profile files."""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, final

_GUARD = threading.Lock()
_HELD: dict[Path, tuple[threading.RLock, int]] = {}
DEFAULT_TIMEOUT = 5.0


@final
class ProfileLockTimeout(TimeoutError):
    """Raised when the role-profile lock cannot be acquired in time."""

    def __init__(self, path: Path) -> None:
        self.path: Path = path
        super().__init__(f"timed out waiting for profile lock: {path}")


def _state(path: Path) -> threading.RLock:
    with _GUARD:
        item = _HELD.get(path)
        if item is None:
            lock = threading.RLock()
            _HELD[path] = (lock, 0)
            return lock
        return item[0]


def _bump(path: Path, delta: int) -> int:
    with _GUARD:
        lock, count = _HELD[path]
        count += delta
        if count <= 0:
            _HELD[path] = (lock, 0)
            return 0
        _HELD[path] = (lock, count)
        return count


def _try_lock_file(handle: BinaryIO) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt

            _ = handle.seek(0)
            _ = msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            _ = fcntl.flock(
                handle.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        return True
    except OSError:
        return False


def _lock_file(handle: BinaryIO, path: Path, timeout: float) -> None:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if _try_lock_file(handle):
            return
        if time.monotonic() >= deadline:
            raise ProfileLockTimeout(path)
        _ = threading.Event().wait(
            min(0.05, max(0.0, deadline - time.monotonic()))
        )


def _unlock_file(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        _ = handle.seek(0)
        _ = msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        _ = fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def profile_lock(
    home: Path,
    timeout: float = DEFAULT_TIMEOUT,
) -> Generator[None, None, None]:
    """Hold the single OS lock covering ``<home>/profile``.

    The lock is reentrant inside one process and is released by the operating
    system if a process exits abruptly. The lock file itself may remain on disk;
    it is only the inode used for advisory locking and is not stale state.
    """
    root = Path(home) / "profile"
    root.mkdir(parents=True, exist_ok=True)
    path = (root / ".profile.lock").resolve()
    local = _state(path)
    with local:
        if _bump(path, 1) > 1:
            try:
                yield
            finally:
                _ = _bump(path, -1)
            return
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, "r+b", buffering=0) as handle:
            acquired = False
            try:
                _lock_file(handle, path, timeout)
                acquired = True
                yield
            finally:
                try:
                    if acquired:
                        _unlock_file(handle)
                finally:
                    _ = _bump(path, -1)
