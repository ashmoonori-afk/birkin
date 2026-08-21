"""The macOS package embeds checksum-pinned native bridge helpers."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parent.parent
INPUTS = REPOSITORY / "scripts/native/bridge_helper_inputs.json"
BUILD_LOCK = REPOSITORY / "scripts/native/bridge_helper_build.lock"
BUILD_SCRIPT = REPOSITORY / "scripts/native/build_bridge_helpers.sh"
BROWSER_BUILD_SCRIPT = REPOSITORY / "scripts/native/build_browser_runtimes.sh"
PACKAGE_SCRIPT = REPOSITORY / "scripts/native/package_macos_app.sh"
DMG_SCRIPT = REPOSITORY / "scripts/native/create_macos_dmg.sh"
_SHA256 = re.compile(r"[0-9a-f]{64}")


def test_helper_build_inputs_pin_both_macos_architectures() -> None:
    # Given the release helper input descriptor.
    descriptor = json.loads(INPUTS.read_text(encoding="utf-8"))

    # When its runtime artifacts are inspected.
    artifacts = descriptor["python"]["artifacts"]

    # Then both app architectures have immutable upstream bytes.
    assert descriptor["schema"] == 1
    assert set(artifacts) == {"arm64", "x86_64"}
    upstream_architectures = {"arm64": "aarch64", "x86_64": "x86_64"}
    for architecture, artifact in artifacts.items():
        assert upstream_architectures[architecture] in artifact["url"]
        assert artifact["url"].startswith(
            "https://github.com/astral-sh/python-build-standalone/releases/download/"
        )
        assert _SHA256.fullmatch(artifact["sha256"])


def test_browser_build_inputs_pin_both_macos_architectures() -> None:
    descriptor = json.loads(INPUTS.read_text(encoding="utf-8"))
    browser = descriptor["browser"]

    assert browser["playwright_version"] == "1.62.0"
    assert browser["chromium_revision"] == "1234"
    assert browser["ffmpeg_revision"] == "1011"
    assert set(browser["artifacts"]) == {"arm64", "x86_64"}
    for artifacts in browser["artifacts"].values():
        assert set(artifacts) == {"headless_shell", "ffmpeg"}
        for artifact in artifacts.values():
            assert artifact["url"].startswith("https://cdn.playwright.dev/")
            assert _SHA256.fullmatch(artifact["sha256"])
            assert artifact["size_bytes"] > 1_000_000


def test_helper_build_toolchain_is_version_and_hash_locked() -> None:
    # Given the dedicated build-only requirements lock.
    lock = BUILD_LOCK.read_text(encoding="utf-8")

    # When its requirement records are read.
    packages = re.findall(r"(?m)^([a-z0-9-]+)==([^ \\;]+)", lock)

    # Then every tool is exact and every record carries an accepted artifact hash.
    assert dict(packages)["pyinstaller"] == "6.22.2"
    assert len(packages) == 8
    assert lock.count("--hash=sha256:") >= len(packages)


def test_helper_builder_verifies_inputs_without_downloading() -> None:
    # Given the checked-in runtime descriptor, build lock, and project lock.
    # When the builder runs its offline input-verification mode.
    result = subprocess.run(
        ["bash", str(BUILD_SCRIPT), "--verify-inputs"],
        cwd=REPOSITORY,
        text=True,
        capture_output=True,
        check=False,
    )

    # Then it reports the exact machine-consumed helper build identity.
    assert result.returncode == 0, result.stdout + result.stderr
    from birkin import __version__

    assert json.loads(result.stdout) == {
        "architectures": ["arm64", "x86_64"],
        "package_version": __version__,
        "python_build": "20260414",
        "python_version": "3.13.13",
        "schema": 1,
    }


def test_browser_builder_verifies_inputs_without_downloading() -> None:
    result = subprocess.run(
        ["bash", str(BROWSER_BUILD_SCRIPT), "--verify-inputs"],
        cwd=REPOSITORY,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "architectures": ["arm64", "x86_64"],
        "chromium_revision": "1234",
        "ffmpeg_revision": "1011",
        "playwright_version": "1.62.0",
    }


def test_package_and_dmg_manifests_publish_helper_identity() -> None:
    # Given the application and disk-image release scripts.
    package_script = PACKAGE_SCRIPT.read_text(encoding="utf-8")
    dmg_script = DMG_SCRIPT.read_text(encoding="utf-8")

    # When their machine-consumed metadata fields are inspected.
    fields = {
        "helper_version",
        "helper_architectures",
        "helper_arm64_sha256",
        "helper_x86_64_sha256",
        "helper_manifest_sha256",
        "helper_python_version",
        "helper_python_build",
        "helper_source_revision",
        "helper_source_state",
        "helper_inputs_sha256",
        "browser_architectures",
        "browser_playwright_version",
        "browser_chromium_revision",
        "browser_ffmpeg_revision",
        "browser_arm64_sha256",
        "browser_arm64_size_bytes",
        "browser_x86_64_sha256",
        "browser_x86_64_size_bytes",
    }

    # Then both release manifests carry the same helper identity and hashes.
    for field in fields:
        assert f"{field}=" in package_script
        assert f"{field}=" in dmg_script
    assert "Contents/Helpers/arm64/birkin-native-bridge" in dmg_script
    assert "Contents/Helpers/x86_64/birkin-native-bridge" in dmg_script
    assert "Contents/Resources/bridge-helper.json" in dmg_script
    builder = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "--collect-all playwright" in builder
    for module in ("docx", "hwpx", "openpyxl", "pptx"):
        assert f"--collect-all {module}" in builder
    assert "build_browser_runtimes.sh" in package_script
    assert "BrowserRuntimes/arm64" in package_script
    assert "BrowserRuntimes/x86_64" in package_script
    assert 'image_size_kib="$((app_size_kib + 262144))"' in dmg_script
