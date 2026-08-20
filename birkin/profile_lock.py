"""OS-level lock for role-profile files."""

from __future__ import annotations

import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

_GUARD = threading.Lock()
_HELD: dict[Path, tuple[threading.RLock, int]] = {}


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


def _lock_file(handle: object) -> None:
    if sys.platform == "win32":
        file = handle  # typing helper
        file.seek(0)  # type: ignore[attr-defined]
        msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)  # type: ignore[attr-defined]
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)  # type: ignore[attr-defined]


def _unlock_file(handle: object) -> None:
    if sys.platform == "win32":
        file = handle
        file.seek(0)  # type: ignore[attr-defined]
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


@contextmanager
def profile_lock(home: Path) -> Iterator[None]:
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
                _bump(path, -1)
            return
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, "r+b", buffering=0) as handle:
            try:
                _lock_file(handle)
                yield
            finally:
                try:
                    _unlock_file(handle)
                finally:
                    _bump(path, -1)
