from __future__ import annotations

import os
import platform
import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "native" / "packaged_journey.sh"

# DiskImages reports lock contention on an image file as EAGAIN and a volume
# it cannot release as EBUSY (hdiutil(1), ERRORS). Both clear once the other
# holder lets go: often the helper of the `hdiutil create` that just returned,
# or a device a failed attach left behind, which is why the image's own
# devices are released before each retry. Any other failure is returned at once.
_HDIUTIL_TRANSIENT = ("Resource temporarily unavailable", "Resource busy")
_HDIUTIL_RETRY_DELAYS = (1, 2, 4)


def _hdiutil(
    *args: str, release: Path | None = None
) -> subprocess.CompletedProcess[bytes]:
    delays = iter(_HDIUTIL_RETRY_DELAYS)
    while True:
        completed = subprocess.run(
            ["/usr/bin/hdiutil", *args],
            capture_output=True,
            check=False,
            timeout=30,
        )
        stderr = completed.stderr.decode(errors="replace")
        delay = next(delays, None)
        if (
            completed.returncode == 0
            or delay is None
            or not any(marker in stderr for marker in _HDIUTIL_TRANSIENT)
        ):
            return completed
        if release is not None:
            _release_image(release)
        time.sleep(delay)


def _release_image(image: Path) -> None:
    """Detach every device DiskImages still has attached for this image."""
    info = _hdiutil("info", "-plist")
    if info.returncode != 0:
        return
    payload = cast(dict[str, object], plistlib.loads(info.stdout))
    target = os.path.realpath(image)
    for image_value in cast(list[object], payload.get("images", [])):
        if not isinstance(image_value, dict):
            continue
        attached = cast(dict[str, object], image_value)
        image_path = attached.get("image-path")
        if not isinstance(image_path, str):
            continue
        if os.path.realpath(image_path) != target:
            continue
        entities = cast(list[object], attached.get("system-entities", []))
        devices = [
            device
            for entity in entities
            if isinstance(entity, dict)
            and isinstance(
                device := cast(dict[str, object], entity).get("dev-entry"), str
            )
        ]
        # The image's own disk is listed first; an APFS image adds a
        # synthesized container disk that detaching the image releases too.
        whole_disk = next(
            (device for device in devices if re.fullmatch(r"/dev/disk\d+", device)),
            None,
        )
        if whole_disk is None:
            continue
        if _hdiutil("detach", whole_disk).returncode != 0:
            _ = _hdiutil("detach", "-force", whole_disk)


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
    create = _hdiutil(
        "create",
        "-volname",
        f"Birkin-Journey-{os.getpid()}",
        "-srcfolder",
        str(source),
        "-format",
        "UDZO",
        "-ov",
        str(image),
    )
    assert create.returncode == 0, create.stderr.decode()

    try:
        attach = _hdiutil(
            "attach", "-nobrowse", "-readonly", "-plist", str(image), release=image
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
        _release_image(image)


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
    create = _hdiutil(
        "create",
        "-volname",
        f"Birkin-Writable-{os.getpid()}",
        "-srcfolder",
        str(source),
        "-format",
        "UDRW",
        "-ov",
        str(image),
    )
    assert create.returncode == 0, create.stderr.decode()

    try:
        attach = _hdiutil("attach", "-nobrowse", "-plist", str(image), release=image)
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
        _release_image(image)
