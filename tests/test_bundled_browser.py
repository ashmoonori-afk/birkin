from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from birkin import __version__
from birkin.bundled_browser import (
    BundledBrowserErrorCode,
    BundledBrowserRuntimeError,
    ensure_bundled_browser,
)


@dataclass(frozen=True)
class BrowserBundleFixture:
    app: Path
    helper: Path
    runtime: Path
    headless: Path
    ffmpeg: Path

    @classmethod
    def create(cls, root: Path) -> BrowserBundleFixture:
        app = root / "Birkin.app"
        helper = app / "Contents/Helpers/arm64/birkin-native-bridge"
        runtime = app / "Contents/Resources/BrowserRuntimes/arm64"
        headless = runtime / "chromium_headless_shell-1234/chrome/chrome-headless-shell"
        ffmpeg = runtime / "ffmpeg-1011/ffmpeg-mac"
        for path in (helper, headless, ffmpeg):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(path.name.encode())
            path.chmod(0o755)
        return cls(app, helper, runtime, headless, ffmpeg)

    def write_manifest(self, *, architecture: str = "arm64") -> None:
        digest, size = _tree_identity(self.runtime)
        record = {
            "schema": 1,
            "package_version": __version__,
            "browser_runtimes": [{
                "architecture": architecture,
                "path": f"BrowserRuntimes/{architecture}",
                "sha256": digest,
                "size_bytes": size,
                "playwright_version": "1.62.0",
                "chromium_revision": "1234",
                "ffmpeg_revision": "1011",
                "headless_executable": (
                    "chromium_headless_shell-1234/chrome/chrome-headless-shell"
                ),
                "ffmpeg_executable": "ffmpeg-1011/ffmpeg-mac",
            }],
        }
        manifest = self.app / "Contents/Resources/bridge-helper.json"
        manifest.write_text(json.dumps(record), encoding="utf-8")


_READ_ONLY_FLAG_VALUE = getattr(os, "ST_RDONLY", None)
_READ_ONLY_FLAG: int = (
    _READ_ONLY_FLAG_VALUE
    if isinstance(_READ_ONLY_FLAG_VALUE, int)
    else 1
)


class _ReadOnlyStat:
    f_flag: int = _READ_ONLY_FLAG


def _read_only_statvfs(
    _path: str | os.PathLike[str],
) -> os.statvfs_result:
    return cast(os.statvfs_result, cast(object, _ReadOnlyStat()))


def _hold_runtime_lease(
    path: str,
    connection: multiprocessing.connection.Connection,
) -> None:
    import fcntl

    with Path(path).open("a+b") as lease:
        fcntl.flock(lease.fileno(), fcntl.LOCK_SH)
        connection.send("ready")
        assert connection.recv() == "release"


def _select_read_only_runtime(
    helper: str,
    home: str,
    connection: multiprocessing.connection.Connection,
) -> None:
    os.environ["BIRKIN_HOME"] = home
    os.statvfs = _read_only_statvfs
    connection.send("ready")
    assert connection.recv() == "start"
    selected = ensure_bundled_browser(
        executable=Path(helper),
        frozen=True,
    )
    connection.send(str(selected))
    assert connection.recv() == "release"


def _tree_identity(root: Path) -> tuple[str, int]:
    tree = hashlib.sha256()
    size = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        relative = "./" + path.relative_to(root).as_posix()
        tree.update(f"{digest}  {relative}\n".encode())
        size += path.stat().st_size
    return tree.hexdigest(), size


def test_frozen_helper_selects_only_verified_bundled_browser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = BrowserBundleFixture.create(tmp_path)
    fixture.write_manifest()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/host/cache/must-not-win")

    selected = ensure_bundled_browser(executable=fixture.helper, frozen=True)

    assert selected == fixture.runtime
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(fixture.runtime)


@pytest.mark.skipif(os.name == "nt", reason="read-only volumes are POSIX")
def test_read_only_bundle_uses_private_verified_runtime_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = BrowserBundleFixture.create(tmp_path / "bundle")
    fixture.write_manifest()
    home = tmp_path / "home"
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    monkeypatch.setattr(
        os,
        "statvfs",
        _read_only_statvfs,
    )

    selected = ensure_bundled_browser(executable=fixture.helper, frozen=True)

    assert selected is not None
    assert selected != fixture.runtime
    assert selected.is_relative_to(home / "browser-runtime-cache")
    assert _tree_identity(selected) == _tree_identity(fixture.runtime)
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(selected)
    assert selected.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(os.name == "nt", reason="read-only volumes are POSIX")
def test_read_only_bundle_rejects_preseeded_cache_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = BrowserBundleFixture.create(tmp_path / "bundle")
    fixture.write_manifest()
    digest, _ = _tree_identity(fixture.runtime)
    home = tmp_path / "home"
    cache = home / "browser-runtime-cache"
    cache.mkdir(parents=True)
    victim = tmp_path / "victim"
    victim.mkdir()
    (cache / f"arm64-{digest}").symlink_to(victim)
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    monkeypatch.setattr(
        os,
        "statvfs",
        _read_only_statvfs,
    )

    with pytest.raises(BundledBrowserRuntimeError) as failure:
        ensure_bundled_browser(executable=fixture.helper, frozen=True)

    assert failure.value.code is BundledBrowserErrorCode.INTEGRITY_FAILED
    assert not any(victim.iterdir())


@pytest.mark.skipif(os.name == "nt", reason="hard links are POSIX")
def test_read_only_bundle_rejects_hard_linked_cache_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = BrowserBundleFixture.create(tmp_path / "bundle")
    fixture.write_manifest()
    digest, _ = _tree_identity(fixture.runtime)
    home = tmp_path / "home"
    target = home / "browser-runtime-cache" / f"arm64-{digest}"
    shutil.copytree(fixture.runtime, target)
    external = tmp_path / "external-link"
    os.link(
        target / fixture.headless.relative_to(fixture.runtime),
        external,
    )
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    monkeypatch.setattr(os, "statvfs", _read_only_statvfs)

    with pytest.raises(BundledBrowserRuntimeError) as failure:
        _ = ensure_bundled_browser(
            executable=fixture.helper,
            frozen=True,
        )

    assert failure.value.code is BundledBrowserErrorCode.INTEGRITY_FAILED


@pytest.mark.skipif(os.name == "nt", reason="read-only volumes are POSIX")
def test_read_only_bundle_prunes_prior_architecture_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = BrowserBundleFixture.create(tmp_path / "bundle")
    fixture.write_manifest()
    home = tmp_path / "home"
    stale = home / "browser-runtime-cache/arm64-stale"
    stale.mkdir(parents=True)
    _ = (stale / "old").write_text("old", encoding="utf-8")
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    monkeypatch.setattr(os, "statvfs", _read_only_statvfs)

    selected = ensure_bundled_browser(
        executable=fixture.helper,
        frozen=True,
    )

    assert selected is not None
    assert not stale.exists()


@pytest.mark.skipif(os.name == "nt", reason="runtime leases require flock")
def test_read_only_bundle_keeps_live_cache_until_lease_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = BrowserBundleFixture.create(tmp_path / "bundle")
    fixture.write_manifest()
    home = tmp_path / "home"
    cache = home / "browser-runtime-cache"
    stale = cache / "arm64-stale"
    stale.mkdir(parents=True)
    _ = (stale / "old").write_text("old", encoding="utf-8")
    lease = cache / ".lease-arm64-stale"
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(
        target=_hold_runtime_lease,
        args=(str(lease), child),
    )
    process.start()
    try:
        assert parent.poll(10)
        assert parent.recv() == "ready"
        monkeypatch.setenv("BIRKIN_HOME", str(home))
        monkeypatch.setattr(os, "statvfs", _read_only_statvfs)

        _ = ensure_bundled_browser(
            executable=fixture.helper,
            frozen=True,
        )

        assert stale.exists()
        parent.send("release")
        process.join(timeout=10)
        assert not process.is_alive()

        _ = ensure_bundled_browser(
            executable=fixture.helper,
            frozen=True,
        )
        assert not stale.exists()
    finally:
        if process.is_alive():
            parent.send("release")
            process.join(timeout=10)
        parent.close()
        child.close()


@pytest.mark.skipif(os.name == "nt", reason="runtime leases require flock")
def test_concurrent_first_publication_returns_to_both_live_processes(
    tmp_path: Path,
) -> None:
    fixture = BrowserBundleFixture.create(tmp_path / "bundle")
    fixture.write_manifest()
    home = tmp_path / "home"
    context = multiprocessing.get_context("spawn")
    channels = [context.Pipe(), context.Pipe()]
    processes = [
        context.Process(
            target=_select_read_only_runtime,
            args=(str(fixture.helper), str(home), child),
        )
        for _, child in channels
    ]
    for process in processes:
        process.start()
    try:
        for parent, _ in channels:
            assert parent.poll(10)
            assert parent.recv() == "ready"
        for parent, _ in channels:
            parent.send("start")
        selected: list[str] = []
        for parent, _ in channels:
            assert parent.poll(10)
            value = parent.recv()
            assert isinstance(value, str)
            selected.append(value)
        assert len(set(selected)) == 1
        assert all(process.is_alive() for process in processes)
    finally:
        for parent, _ in channels:
            parent.send("release")
        for process in processes:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)
        for parent, child in channels:
            parent.close()
            child.close()


@pytest.mark.skipif(os.name == "nt", reason="runtime leases require flock")
def test_repeated_selection_reuses_one_process_lifetime_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin import bundled_browser_cache

    fixture = BrowserBundleFixture.create(tmp_path / "bundle")
    fixture.write_manifest()
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(os, "statvfs", _read_only_statvfs)
    before = len(bundled_browser_cache._RUNTIME_LEASES)

    for _ in range(20):
        _ = ensure_bundled_browser(
            executable=fixture.helper,
            frozen=True,
        )

    assert len(bundled_browser_cache._RUNTIME_LEASES) == before + 1


def test_missing_bundled_browser_fails_closed_with_bounded_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = BrowserBundleFixture.create(tmp_path)
    fixture.write_manifest()
    shutil.rmtree(fixture.runtime)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/host/cache/must-not-win")

    with pytest.raises(BundledBrowserRuntimeError) as failure:
        ensure_bundled_browser(executable=fixture.helper, frozen=True)

    assert failure.value.code is BundledBrowserErrorCode.RUNTIME_MISSING
    assert len(str(failure.value)) <= 160
    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


def test_malformed_runtime_record_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = BrowserBundleFixture.create(tmp_path)
    fixture.write_manifest()
    manifest = fixture.app / "Contents/Resources/bridge-helper.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["browser_runtimes"][0]["size_bytes"] = "not-an-integer"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/host/cache/must-not-win")

    with pytest.raises(BundledBrowserRuntimeError) as failure:
        ensure_bundled_browser(executable=fixture.helper, frozen=True)

    assert failure.value.code is BundledBrowserErrorCode.MANIFEST_INVALID
    assert len(str(failure.value)) <= 160
    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


def test_other_architecture_is_never_selected_as_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = BrowserBundleFixture.create(tmp_path)
    fixture.write_manifest(architecture="x86_64")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/host/cache/must-not-win")

    with pytest.raises(BundledBrowserRuntimeError) as failure:
        ensure_bundled_browser(executable=fixture.helper, frozen=True)

    assert failure.value.code is BundledBrowserErrorCode.ARCHITECTURE_MISSING
    assert len(str(failure.value)) <= 160
    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


def test_tampered_bundled_browser_fails_closed_with_bounded_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = BrowserBundleFixture.create(tmp_path)
    fixture.write_manifest()
    fixture.headless.write_bytes(b"tampered")
    fixture.headless.chmod(0o755)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/host/cache/must-not-win")

    with pytest.raises(BundledBrowserRuntimeError) as failure:
        ensure_bundled_browser(executable=fixture.helper, frozen=True)

    assert failure.value.code is BundledBrowserErrorCode.INTEGRITY_FAILED
    assert len(str(failure.value)) <= 160
    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ
