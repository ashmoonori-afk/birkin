from __future__ import annotations

import os
from pathlib import Path

import pytest

from birkin.browser_aside_profiles import (
    clear_profile_lock,
    profile_lock_target,
    profile_owner_lock,
    purge_stale_profiles,
)
from birkin.store import FileLockTimeout, file_lock


def test_profile_sweep_skips_live_owner_then_purges_stale_owner(
    tmp_path: Path,
) -> None:
    profiles = tmp_path / "profiles"
    stale = profiles / "stale"
    live = profiles / "live"
    stale.mkdir(parents=True)
    live.mkdir()
    _ = (stale / "cookie").write_text("private", encoding="utf-8")
    lock = file_lock(profile_lock_target(live), timeout=0)
    _ = lock.__enter__()
    try:
        assert purge_stale_profiles(profiles) == 1
        assert not stale.exists()
        assert live.exists()
    finally:
        lock.__exit__(None, None, None)
    assert purge_stale_profiles(profiles) == 1
    assert not live.exists()


def test_profile_sweep_unlinks_symlink_without_touching_target(
    tmp_path: Path,
) -> None:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "private"
    _ = marker.write_text("keep", encoding="utf-8")
    try:
        (profiles / "escape").symlink_to(
            outside,
            target_is_directory=True,
        )
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    assert purge_stale_profiles(profiles) == 1
    assert marker.read_text(encoding="utf-8") == "keep"


def test_owner_lock_precedes_profile_visibility(
    tmp_path: Path,
) -> None:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    profile = profiles / "starting"
    with profile_owner_lock(profile):
        profile.mkdir()
        assert purge_stale_profiles(profiles) == 0
        assert profile.exists()
    assert purge_stale_profiles(profiles) == 1


def test_profile_sweep_ignores_path_removed_before_inspection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profiles = tmp_path / "profiles"
    profile = profiles / "vanished"
    profile.mkdir(parents=True)
    original_lstat = Path.lstat

    def remove_before_lstat(path: Path) -> os.stat_result:
        if path == profile:
            os.rmdir(path)
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", remove_before_lstat)
    assert purge_stale_profiles(profiles) == 0


def test_profile_lock_inode_remains_stable_across_clear(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profiles" / "stable"
    profile.parent.mkdir()
    target = profile_lock_target(profile)
    first = file_lock(target, timeout=0)
    _ = first.__enter__()
    lock_path = Path(f"{target}.lock")
    inode = lock_path.stat().st_ino
    try:
        clear_profile_lock(profile)
        second = file_lock(target, timeout=0)
        with pytest.raises(FileLockTimeout):
            _ = second.__enter__()
        assert lock_path.stat().st_ino == inode
    finally:
        first.__exit__(None, None, None)


def test_clear_profile_lock_creates_persistent_private_inode(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profiles" / "new"
    profile.parent.mkdir()

    clear_profile_lock(profile)

    lock_path = Path(f"{profile_lock_target(profile)}.lock")
    assert lock_path.is_file()
    assert lock_path.stat().st_mode & 0o777 == 0o600
