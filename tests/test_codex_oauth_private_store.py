from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Protocol

import pytest


class _StoreWriter(Protocol):
    def __call__(self, tokens: dict[str, str]) -> None: ...


def _stored_access(path: Path) -> str:
    match = re.search(
        r'"access_token"\s*:\s*"([^"]*)"',
        path.read_text(encoding="utf-8"),
    )
    if match is None:
        raise AssertionError("stored credential does not have the expected shape")
    return match.group(1)


def _write_numbered(writer: _StoreWriter, index: int) -> None:
    writer({
        "access_token": f"SYNTHETIC-{index}",
        "refresh_token": f"R-{index}",
    })


def test_fixed_temp_symlink_victim_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from birkin import codex_oauth

    store = tmp_path / "codex-auth.json"
    victim = tmp_path / "victim"
    _ = victim.write_text("UNCHANGED", encoding="utf-8")
    store.with_suffix(".tmp").symlink_to(victim)
    monkeypatch.setattr(codex_oauth, "store_path", lambda: store)

    codex_oauth.write_store({"access_token": "SYNTHETIC", "refresh_token": "R"})

    assert victim.read_text(encoding="utf-8") == "UNCHANGED"
    assert _stored_access(store) == "SYNTHETIC"


@pytest.mark.skipif(os.name == "nt", reason="POSIX creation mode")
def test_private_mode_exists_at_creation_and_names_are_unpredictable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from birkin import codex_oauth

    store = tmp_path / "codex-auth.json"
    monkeypatch.setattr(codex_oauth, "store_path", lambda: store)
    seen: list[tuple[str, int]] = []
    real_fsync = os.fsync

    def inspect_fsync(fd: int) -> None:
        metadata = os.fstat(fd)
        if stat.S_ISREG(metadata.st_mode):
            links = list(tmp_path.iterdir())
            residue = [p for p in links if p.name.startswith(".codex-auth.json.")]
            if residue:
                seen.append((residue[0].name, stat.S_IMODE(residue[0].stat().st_mode)))
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", inspect_fsync)
    codex_oauth.write_store({"access_token": "SYNTHETIC", "refresh_token": "R"})

    assert seen and seen[0][1] == 0o600
    assert seen[0][0] != "codex-auth.tmp"
    assert stat.S_IMODE(store.stat().st_mode) == 0o600


def test_concurrent_writers_publish_only_complete_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from birkin import codex_oauth

    store = tmp_path / "codex-auth.json"
    monkeypatch.setattr(codex_oauth, "store_path", lambda: store)
    def write_numbered(index: int) -> None:
        _write_numbered(codex_oauth.write_store, index)

    with ThreadPoolExecutor(max_workers=8) as pool:
        completed = pool.map(write_numbered, range(32))
        assert list(completed) == [None] * 32
    assert _stored_access(store).startswith("SYNTHETIC-")
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".codex-auth.json.")]


@pytest.mark.skipif(os.name == "nt", reason="POSIX abrupt-exit mode evidence")
def test_abrupt_exit_leaves_only_private_unpredictable_residue(tmp_path: Path) -> None:
    script = """
import os
from birkin import codex_oauth
codex_oauth.os.replace = lambda *args: os._exit(73)
codex_oauth.write_store({'access_token': 'SYNTHETIC-CRASH', 'refresh_token': 'R'})
"""
    env = {**os.environ, "BIRKIN_HOME": str(tmp_path)}
    done = subprocess.run([sys.executable, "-c", script], env=env, check=False)
    assert done.returncode == 73
    residue = [p for p in tmp_path.iterdir() if p.name.startswith(".codex-auth.json.")]
    assert len(residue) == 1
    assert residue[0].name != "codex-auth.tmp"
    assert stat.S_IMODE(residue[0].stat().st_mode) == 0o600


def test_failed_publish_preserves_old_valid_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from birkin import codex_oauth

    store = tmp_path / "codex-auth.json"
    old = {"tokens": {"access_token": "OLD", "refresh_token": "OLD-R"}}
    _ = store.write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(codex_oauth, "store_path", lambda: store)

    def fail_replace(_source: os.PathLike[str], _destination: os.PathLike[str]) -> None:
        raise OSError("crash")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError):
        codex_oauth.write_store({"access_token": "NEW", "refresh_token": "NEW-R"})

    assert _stored_access(store) == "OLD"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".codex-auth.json.")]
