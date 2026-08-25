"""Crash-safe isolated profile cleanup backed by OS advisory locks."""

from __future__ import annotations

import shutil
import stat
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from birkin.browser_aside_errors import BrowserAsideError
from birkin.native.private_storage import (
    harden_private_directory,
    harden_private_file,
)
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
    return purged


def profile_lock_target(profile: Path) -> Path:
    root = profile.parent.resolve()
    locks = root / ".locks"
    harden_private_directory(locks)
    return locks / profile.name


def clear_profile_lock(profile: Path) -> None:
    """Retain the advisory-lock inode permanently after owner release."""
    target = profile_lock_target(profile)
    lock_path = Path(f"{target}.lock")
    lock_path.touch(mode=0o600, exist_ok=True)
    harden_private_file(lock_path)


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
