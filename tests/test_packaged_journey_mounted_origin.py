from __future__ import annotations

import os
import platform
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "native" / "packaged_journey.sh"


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="mounted DMG provenance requires hdiutil",
)
def test_journey_accepts_app_from_attached_disk_image(tmp_path: Path) -> None:
    source = tmp_path / "source"
    app = source / "Birkin.app/Contents/MacOS/BirkinNativeApp"
    architecture = {
        "arm64": "arm64",
        "aarch64": "arm64",
        "x86_64": "x86_64",
    }[platform.machine()]
    helper = (
        source
        / "Birkin.app"
        / "Contents"
        / "Helpers"
        / architecture
        / "birkin-native-bridge"
    )
    app.parent.mkdir(parents=True)
    helper.parent.mkdir(parents=True)
    _ = helper.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    _ = app.write_text(
        """#!/bin/bash
{
  printf 'origin=%s\n' "$BIRKIN_NATIVE_JOURNEY_ORIGIN"
  printf 'mount=%s\n' "$BIRKIN_NATIVE_JOURNEY_MOUNT"
  printf 'image=%s\n' "$BIRKIN_NATIVE_JOURNEY_IMAGE"
  printf 'executable=%s\n' "$0"
} > "$BIRKIN_NATIVE_JOURNEY_EVIDENCE/origin-provenance"
exit 73
""",
        encoding="utf-8",
    )
    _ = helper.chmod(0o755)
    _ = app.chmod(0o755)
    image = tmp_path / "Birkin-Journey-Test.dmg"
    create = subprocess.run(
        [
            "/usr/bin/hdiutil",
            "create",
            "-volname",
            f"Birkin-Journey-{os.getpid()}",
            "-srcfolder",
            str(source),
            "-format",
            "UDZO",
            "-ov",
            str(image),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert create.returncode == 0, create.stderr

    attach = subprocess.run(
        [
            "/usr/bin/hdiutil",
            "attach",
            "-nobrowse",
            "-readonly",
            "-plist",
            str(image),
        ],
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert attach.returncode == 0, attach.stderr.decode()
    payload = cast(dict[str, object], plistlib.loads(attach.stdout))
    entities_value = payload.get("system-entities")
    assert isinstance(entities_value, list)
    mount: str | None = None
    for entity_value in cast(list[object], entities_value):
        assert isinstance(entity_value, dict)
        entity = cast(dict[str, object], entity_value)
        candidate = entity.get("mount-point")
        if isinstance(candidate, str):
            mount = candidate
            break
    assert mount is not None
    evidence = tmp_path / "evidence"
    try:
        result = subprocess.run(
            ["bash", str(SCRIPT), str(evidence), mount],
            cwd=ROOT,
            env={
                **os.environ,
                "BIRKIN_NATIVE_JOURNEY_ORIGIN": "mounted-dmg",
            },
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        assert result.returncode != 2, result.stderr
        provenance = dict(
            line.split("=", 1)
            for line in (evidence / "origin-provenance")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        assert Path(provenance["mount"]).resolve() == Path(mount).resolve()
        assert Path(provenance["image"]).resolve() == image.resolve()
        assert Path(provenance["executable"]).resolve().is_relative_to(
            Path(mount).resolve()
        )
    finally:
        _ = subprocess.run(
            ["/usr/bin/hdiutil", "detach", mount],
            capture_output=True,
            check=False,
            timeout=30,
        )


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="mounted DMG provenance requires hdiutil",
)
def test_journey_rejects_app_from_writable_disk_image(tmp_path: Path) -> None:
    source = tmp_path / "source"
    app = source / "Birkin.app/Contents/MacOS/BirkinNativeApp"
    architecture = {
        "arm64": "arm64",
        "aarch64": "arm64",
        "x86_64": "x86_64",
    }[platform.machine()]
    helper = (
        source
        / "Birkin.app"
        / "Contents"
        / "Helpers"
        / architecture
        / "birkin-native-bridge"
    )
    app.parent.mkdir(parents=True)
    helper.parent.mkdir(parents=True)
    _ = helper.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    _ = app.write_text("#!/bin/bash\nexit 73\n", encoding="utf-8")
    helper.chmod(0o755)
    app.chmod(0o755)
    image = tmp_path / "Birkin-Journey-Writable.dmg"
    create = subprocess.run(
        [
            "/usr/bin/hdiutil",
            "create",
            "-volname",
            f"Birkin-Writable-{os.getpid()}",
            "-srcfolder",
            str(source),
            "-format",
            "UDRW",
            "-ov",
            str(image),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert create.returncode == 0, create.stderr

    attach = subprocess.run(
        [
            "/usr/bin/hdiutil",
            "attach",
            "-nobrowse",
            "-plist",
            str(image),
        ],
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert attach.returncode == 0, attach.stderr.decode()
    payload = cast(dict[str, object], plistlib.loads(attach.stdout))
    entities_value = payload.get("system-entities")
    assert isinstance(entities_value, list)
    mount = next(
        (
            candidate
            for entity_value in cast(list[object], entities_value)
            if isinstance(entity_value, dict)
            and isinstance(
                candidate := cast(dict[str, object], entity_value).get(
                    "mount-point"
                ),
                str,
            )
        ),
        None,
    )
    assert isinstance(mount, str)
    try:
        result = subprocess.run(
            ["bash", str(SCRIPT), str(tmp_path / "evidence"), mount],
            cwd=ROOT,
            env={
                **os.environ,
                "BIRKIN_NATIVE_JOURNEY_ORIGIN": "mounted-dmg",
            },
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "read-only" in result.stderr
    finally:
        _ = subprocess.run(
            ["/usr/bin/hdiutil", "detach", mount],
            capture_output=True,
            check=False,
            timeout=30,
        )
