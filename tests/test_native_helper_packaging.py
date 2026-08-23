"""The macOS package embeds checksum-pinned native bridge helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TypeGuard, cast

import pytest
import tomli

REPOSITORY = Path(__file__).resolve().parent.parent
INPUTS = REPOSITORY / "scripts/native/bridge_helper_inputs.json"
BUILD_LOCK = REPOSITORY / "scripts/native/bridge_helper_build.lock"
BUILD_SCRIPT = REPOSITORY / "scripts/native/build_bridge_helpers.sh"
BROWSER_BUILD_SCRIPT = REPOSITORY / "scripts/native/build_browser_runtimes.sh"
PACKAGE_SCRIPT = REPOSITORY / "scripts/native/package_macos_app.sh"
DMG_SCRIPT = REPOSITORY / "scripts/native/create_macos_dmg.sh"
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _script_environment() -> dict[str, str]:
    return {
        **os.environ,
        "BIRKIN_VERIFY_PYTHON": Path(sys.executable).as_posix(),
    }


def _is_string_keyed_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _read_json_object(path: Path) -> dict[str, object]:
    decoded = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if not _is_string_keyed_object(decoded):
        raise AssertionError(f"{path} must contain a JSON object")
    return decoded


def _object(value: object) -> dict[str, object]:
    assert _is_string_keyed_object(value)
    return value


def _string(value: object) -> str:
    assert isinstance(value, str)
    return value


def _integer(value: object) -> int:
    assert type(value) is int
    return value


def test_helper_build_inputs_pin_both_macos_architectures() -> None:
    # Given the release helper input descriptor.
    descriptor = _read_json_object(INPUTS)

    # When its runtime artifacts are inspected.
    artifacts = _object(_object(descriptor["python"])["artifacts"])

    # Then both app architectures have immutable upstream bytes.
    assert _integer(descriptor["schema"]) == 1
    assert set(artifacts) == {"arm64", "x86_64"}
    upstream_architectures = {"arm64": "aarch64", "x86_64": "x86_64"}
    for architecture, artifact_value in artifacts.items():
        artifact = _object(artifact_value)
        url = _string(artifact["url"])
        assert upstream_architectures[architecture] in url
        assert url.startswith(
            "https://github.com/astral-sh/python-build-standalone/releases/download/"
        )
        assert _SHA256.fullmatch(_string(artifact["sha256"]))


def test_helper_project_and_lock_inputs_are_checksum_pinned() -> None:
    descriptor = _read_json_object(INPUTS)
    project = _object(descriptor["project"])

    assert project == {
        "pyproject_sha256": hashlib.sha256(
            (REPOSITORY / "pyproject.toml")
            .read_bytes()
            .replace(b"\r\n", b"\n")
        ).hexdigest(),
        "uv_lock_sha256": hashlib.sha256(
            (REPOSITORY / "uv.lock").read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest(),
    }


def test_browser_build_inputs_pin_both_macos_architectures() -> None:
    descriptor = _read_json_object(INPUTS)
    browser = _object(descriptor["browser"])

    assert _string(browser["playwright_version"]) == "1.62.0"
    assert _string(browser["chromium_revision"]) == "1234"
    assert _string(browser["ffmpeg_revision"]) == "1011"
    browser_artifacts = _object(browser["artifacts"])
    assert set(browser_artifacts) == {"arm64", "x86_64"}
    for artifacts_value in browser_artifacts.values():
        artifacts = _object(artifacts_value)
        assert set(artifacts) == {"headless_shell", "ffmpeg"}
        for artifact_value in artifacts.values():
            artifact = _object(artifact_value)
            assert _string(artifact["url"]).startswith("https://cdn.playwright.dev/")
            assert _SHA256.fullmatch(_string(artifact["sha256"]))
            assert _integer(artifact["size_bytes"]) > 1_000_000


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
        env=_script_environment(),
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


def _copy_verifier_repository(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    native_scripts = repository / "scripts/native"
    native_scripts.mkdir(parents=True)
    for source in (INPUTS, BUILD_LOCK, BUILD_SCRIPT):
        _ = shutil.copy2(source, native_scripts / source.name)
    for source_name in ("pyproject.toml", "uv.lock"):
        _ = shutil.copy2(REPOSITORY / source_name, repository / source_name)
    return repository, native_scripts / BUILD_SCRIPT.name


@pytest.mark.parametrize("target_name", ["pyproject.toml", "uv.lock"])
def test_helper_builder_rejects_changed_project_lock_inputs(
    tmp_path: Path,
    target_name: str,
) -> None:
    repository, build_script = _copy_verifier_repository(tmp_path)

    target = repository / target_name
    _ = target.write_bytes(target.read_bytes() + b"\n# tampered\n")
    result = subprocess.run(
        ["bash", str(build_script), "--verify-inputs"],
        cwd=repository,
        env=_script_environment(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0


def test_helper_builder_accepts_checkout_line_endings(tmp_path: Path) -> None:
    repository, build_script = _copy_verifier_repository(tmp_path)
    for source_name in ("pyproject.toml", "uv.lock"):
        source = repository / source_name
        _ = source.write_bytes(source.read_bytes().replace(b"\n", b"\r\n"))

    result = subprocess.run(
        ["bash", str(build_script), "--verify-inputs"],
        cwd=repository,
        env=_script_environment(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("script", [BUILD_SCRIPT, BROWSER_BUILD_SCRIPT])
def test_builder_rejects_missing_explicit_python(script: Path) -> None:
    result = subprocess.run(
        ["bash", str(script), "--verify-inputs"],
        cwd=REPOSITORY,
        env={
            **os.environ,
            "BIRKIN_VERIFY_PYTHON": "/missing/birkin-python",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0


def test_helper_builder_normalizes_msys_interpreter_path(
    tmp_path: Path,
) -> None:
    repository, build_script = _copy_verifier_repository(tmp_path)
    tools = tmp_path / "tools"
    tools.mkdir()
    uname = tools / "uname"
    _ = uname.write_text("#!/bin/sh\nprintf 'MINGW64_NT\\n'\n", encoding="utf-8")
    uname.chmod(0o755)
    cygpath = tools / "cygpath"
    _ = cygpath.write_text(
        f"#!/bin/sh\nprintf '%s\\n' '{Path(sys.executable).as_posix()}'\n",
        encoding="utf-8",
    )
    cygpath.chmod(0o755)

    result = subprocess.run(
        ["bash", str(build_script), "--verify-inputs"],
        cwd=repository,
        env={
            **os.environ,
            "BIRKIN_VERIFY_PYTHON": r"C:\Birkin\python.exe",
            "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_helper_runtime_hash_policy_accepts_only_exact_vcs_source() -> None:
    # Given the exact locked runtime dependency graph.
    with (REPOSITORY / "uv.lock").open("rb") as lock_file:
        lock = cast(dict[str, object], tomli.load(lock_file))
    packages = cast(list[dict[str, object]], lock["package"])

    # When immutable VCS sources and their installer policy are inspected.
    vcs_sources = [
        (cast(str, package["name"]), cast(dict[str, str], package["source"]))
        for package in packages
        if isinstance(package.get("source"), dict)
        and "git" in cast(dict[str, object], package["source"])
    ]
    runtime_install = re.search(
        r'uv pip install[^\n]*\\\n\s+--requirements "\$work/runtime\.lock"',
        BUILD_SCRIPT.read_text(encoding="utf-8"),
    )

    # Then only the immutable Git source bypasses all-record hash enforcement.
    assert vcs_sources == [(
        "birkin-mnemosyne",
        {
            "git": (
                "https://github.com/ashmoonori-afk/birkin-mnemosyne"
                + "?rev=36814c13b44260a0c1ada53d142b2940fff134df"
                + "#36814c13b44260a0c1ada53d142b2940fff134df"
            ),
        },
    )]
    assert runtime_install is not None
    assert "--require-hashes" not in runtime_install.group()


def test_helper_builder_signs_extracted_runtime_before_execution() -> None:
    builder = BUILD_SCRIPT.read_text(encoding="utf-8")

    signing = builder.index('/usr/bin/codesign --force --sign - "$binary"')
    runtime_execution = builder.index('uv pip install --python "$python"')

    assert signing < runtime_execution
    assert '/usr/bin/codesign --verify "$python"' in builder


def test_browser_builder_verifies_inputs_without_downloading() -> None:
    result = subprocess.run(
        ["bash", str(BROWSER_BUILD_SCRIPT), "--verify-inputs"],
        cwd=REPOSITORY,
        env=_script_environment(),
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
