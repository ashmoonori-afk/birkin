"""Crash-safe isolated profile cleanup backed by OS advisory locks."""

from __future__ import annotations

import shutil
import stat
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from birkin.browser_aside_errors import BrowserAsideError
from birkin.store import FileLockTimeout, file_lock


def purge_stale_profiles(profiles_root: Path) -> int:
    purged = 0
    for profile in tuple(profiles_root.iterdir()):
        try:
            metadata = profile.lstat()
            mode = metadata.st_mode
            if stat.S_ISLNK(mode):
                profile.unlink()
                purged += 1
                continue
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(mode) or profile.name == ".locks":
            continue
        lock_target = profile_lock_target(profile)
        lock = file_lock(lock_target, timeout=0)
        try:
            _ = lock.__enter__()
        except FileLockTimeout:
            continue
        try:
            current = profile.lstat()
            if (
                current.st_dev != metadata.st_dev
                or current.st_ino != metadata.st_ino
            ):
                continue
            shutil.rmtree(profile)
            purged += 1
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise BrowserAsideError(
                "browser_profile_cleanup_failed",
                "Stale browser profile cleanup failed.",
                500,
            ) from exc
        finally:
            lock.__exit__(None, None, None)
        Path(f"{lock_target}.lock").unlink(missing_ok=True)
    return purged


def profile_lock_target(profile: Path) -> Path:
    root = profile.parent.resolve()
    locks = root / ".locks"
    locks.mkdir(mode=0o700, exist_ok=True)
    locks.chmod(0o700)
    return locks / profile.name


def clear_profile_lock(profile: Path) -> None:
    target = profile_lock_target(profile)
    Path(f"{target}.lock").unlink(missing_ok=True)


@contextmanager
def profile_owner_lock(profile: Path) -> Generator[None]:
    lock = file_lock(profile_lock_target(profile), timeout=0.1)
    try:
        _ = lock.__enter__()
    except FileLockTimeout as exc:
        raise BrowserAsideError(
            "browser_profile_locked",
            "Browser profile is owned by another process.",
            409,
        ) from exc
    try:
        yield
    finally:
        lock.__exit__(None, None, None)
