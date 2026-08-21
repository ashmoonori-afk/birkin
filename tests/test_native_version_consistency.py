"""One package version drives every shipped native identity."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parent.parent
SWIFT_VERSION = (
    REPOSITORY
    / "macos/BirkinNativeApp/Sources/BirkinNativeProtocol/BirkinVersion.swift"
)
GOLDEN_VECTORS = (
    REPOSITORY
    / "macos/BirkinNativeApp/Tests/BirkinNativeProtocolTests"
    / "GoldenVectors/native-protocol-vectors.json"
)
DMG_SCRIPT = REPOSITORY / "scripts/native/create_macos_dmg.sh"
_SEMVER = re.compile(r"\d+\.\d+\.\d+")


def _package_version() -> str:
    with (REPOSITORY / "pyproject.toml").open("rb") as handle:
        manifest = tomllib.load(handle)
    project = manifest["project"]
    assert isinstance(project, dict)
    version = project["version"]
    assert isinstance(version, str)
    return version


def test_python_package_and_module_version_agree() -> None:
    """Given the manifest version, When the package is imported, Then the
    module reports the same version."""
    import birkin

    assert birkin.__version__ == _package_version()


def test_generated_swift_version_matches_the_manifest() -> None:
    """Given the generated Swift version seam, When it is read, Then it
    carries exactly the manifest version."""
    generated = SWIFT_VERSION.read_text(encoding="utf-8")

    found = _SEMVER.findall(generated)

    assert found == [_package_version()]


def test_version_sync_reports_a_current_tree() -> None:
    """Given the shipped sync tool, When it checks the tree, Then it reports
    the generated seam is current."""
    result = subprocess.run(
        [sys.executable, "scripts/native/sync_version.py", "--check"],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_golden_vectors_advertise_the_manifest_version() -> None:
    """Given the generated protocol vectors, When the ready frame is read,
    Then its server_version is the manifest version."""
    vectors = json.loads(GOLDEN_VECTORS.read_text(encoding="utf-8"))
    assert isinstance(vectors, dict)

    ready = [
        record
        for record in vectors["vectors"]
        if record["envelope"]["kind"] == "ready"
    ]

    assert ready, "no ready vector was generated"
    for record in ready:
        assert record["envelope"]["body"]["server_version"] == _package_version()


def test_disk_image_name_is_derived_not_pinned() -> None:
    """Given the packaging script, When it names the disk image, Then the name
    comes from the manifest instead of a pinned literal."""
    script = DMG_SCRIPT.read_text(encoding="utf-8")

    assert "pyproject.toml" in script
    assert not _SEMVER.search(script), "the disk image name pins a version"


def test_disk_image_manifests_follow_the_requested_output_root() -> None:
    """Given the packaging script, When it records artifact manifests, Then it
    writes them beside the requested distribution root instead of a fixed
    evidence phase directory."""
    script = DMG_SCRIPT.read_text(encoding="utf-8")

    pinned = [
        line
        for line in script.splitlines()
        if re.match(r"\s*(build_)?manifest=", line) and "$output_root" not in line
    ]

    assert pinned == [], f"manifest paths do not follow the output root: {pinned}"
    assert 'manifest="$output_root' in script
    assert 'build_manifest="$output_root' in script
