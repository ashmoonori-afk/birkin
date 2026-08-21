from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

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
