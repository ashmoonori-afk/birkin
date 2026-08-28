from __future__ import annotations

import os
from pathlib import Path

import pytest

from birkin import config, private_storage


def test_birkin_home_hardens_each_root_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first-home"
    second = tmp_path / "second-home"
    calls: list[Path] = []

    def harden(path: Path) -> None:
        calls.append(path)
        path.mkdir()

    monkeypatch.setattr(
        private_storage,
        "harden_private_directory",
        harden,
    )
    config.clear_birkin_home_cache()
    monkeypatch.setenv("BIRKIN_HOME", str(first))

    assert config.birkin_home() == first
    assert config.birkin_home() == first
    monkeypatch.setenv("BIRKIN_HOME", str(second))
    assert config.birkin_home() == second

    assert calls == [first, second]


def test_birkin_home_rejects_replaced_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    config.clear_birkin_home_cache()
    assert config.birkin_home() == home

    replacement = tmp_path / "replacement"
    replacement.mkdir(mode=0o755)
    home.rename(tmp_path / "retired-home")
    replacement.rename(home)

    with pytest.raises(OSError, match="changed after hardening"):
        _ = config.pending_dir()


def test_birkin_home_normalizes_relative_root_before_hardening(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BIRKIN_HOME", "relative-home")
    config.clear_birkin_home_cache()

    expected = tmp_path / "relative-home"
    assert config.birkin_home() == expected
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    assert config.birkin_home() == expected


def test_birkin_home_rejects_symlinked_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    linked = tmp_path / "linked-home"
    linked.symlink_to(target, target_is_directory=True)
    monkeypatch.setenv("BIRKIN_HOME", str(linked))
    config.clear_birkin_home_cache()

    with pytest.raises(OSError, match="real directory"):
        _ = config.birkin_home()


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner-control contract")
def test_birkin_home_rejects_shared_writable_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "shared"
    parent.mkdir(mode=0o777)
    parent.chmod(0o777)
    monkeypatch.setenv("BIRKIN_HOME", str(parent / "home"))
    config.clear_birkin_home_cache()

    with pytest.raises(OSError, match="owner-controlled"):
        _ = config.birkin_home()
