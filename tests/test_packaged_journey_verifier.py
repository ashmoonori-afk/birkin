from __future__ import annotations

import hashlib
import importlib
import json
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from typing import TypeAlias, cast

import pytest

from scripts.native.packaged_evidence_io import (
    CRITICAL_JOURNEY_STEPS,
    REQUIRED_JOURNEY_STEPS,
)

JSONValue: TypeAlias = (
    str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
)
SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "native"
    / "verify_packaged_journey.py"
)
REQUIRED_STEPS = tuple(sorted(REQUIRED_JOURNEY_STEPS | {"working-memory-clear"}))
CRITICAL_STEPS = tuple(sorted(CRITICAL_JOURNEY_STEPS))
NONCRITICAL_STEP = next(
    name for name in REQUIRED_STEPS if name not in CRITICAL_JOURNEY_STEPS
)
SANITIZED_SEARCH_PATH = (
    "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
)


def _run(*arguments: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(str(value) for value in arguments)],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )


def _png_bytes(seed: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFF_FFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    width = 128
    height = 128
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels = bytearray()
    for y in range(height):
        pixels.append(0)
        for x in range(width):
            pixels.extend((
                (seed + x * 7) % 256,
                (255 - seed + y * 11) % 256,
                (seed + x * 3 + y * 5) % 256,
            ))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(pixels)))
        + chunk(b"IEND", b"")
    )


def _write_fixture(
    root: Path,
    *,
    invalid_bridge_identity: bool = False,
    escaping_screenshot: bool = False,
    linked_probe_outside: bool = False,
    linked_receipt_outside: bool = False,
    linked_screenshot_inside: bool = False,
    invalid_png: bool = False,
    missing_focus_generation: bool = False,
    missing_cjk_ocr_markers: bool = False,
    missing_noncritical_screenshot: bool = False,
    unsafe_search_path: bool = False,
    forged_mounted_origin: bool = False,
) -> tuple[Path, Path, Path]:
    evidence = root / "evidence"
    workspace = root / "workspace"
    helper = (
        root
        / "dist"
        / "Birkin.app"
        / "Contents"
        / "Helpers"
        / "arm64"
        / "birkin-native-bridge"
    )
    browser = (
        helper.parents[2]
        / "Resources"
        / "BrowserRuntimes"
        / helper.parent.name
    )
    app_executable = helper.parents[2] / "MacOS" / "BirkinNativeApp"
    evidence.mkdir(parents=True)
    workspace.mkdir()
    helper.parent.mkdir(parents=True)
    _ = helper.write_text("fixture", encoding="utf-8")
    browser.mkdir(parents=True)
    app_executable.parent.mkdir(parents=True)
    _ = app_executable.write_text("fixture", encoding="utf-8")

    steps: list[JSONValue] = []
    for index, name in enumerate(REQUIRED_STEPS):
        detail = f"{name} 한국어 日本語 漢字"
        if name == "chat-send-stream":
            detail += " provider_completion=PACKAGED_PROVIDER_COMPLETION_OK"
        step: dict[str, JSONValue] = {
            "detail": detail,
            "name": name,
            "screenshot": "",
            "succeeded": True,
            "surface": f"section:{name}",
        }
        if not (missing_noncritical_screenshot and name == NONCRITICAL_STEP):
            screenshot = evidence / f"{index}-{name}.png"
            screenshot_bytes = (
                bytes([index + 1]) * 4_096
                if invalid_png and name == "chat-send-stream"
                else _png_bytes(index + 1)
            )
            _ = screenshot.write_bytes(screenshot_bytes)
            if escaping_screenshot and name == "chat-send-stream":
                escaped = root / "outside.png"
                _ = escaped.write_bytes(_png_bytes(index + 1))
                step["screenshot"] = "../outside.png"
            else:
                step["screenshot"] = screenshot.name
            step["capture"] = {
                "cjk_ocr_markers": (
                    []
                    if missing_cjk_ocr_markers
                    else ["한국어", "日本語", "漢字"]
                ),
                "executable_path": str(app_executable.resolve()),
                "focus_generation": index + 1,
                "focus_target": step["surface"],
                "owner_pid": 123,
                "pixel_height": 1_600,
                "pixel_width": 2_560,
                "point_height": 800,
                "point_width": 1_280,
                "png_sha256": hashlib.sha256(screenshot_bytes).hexdigest(),
                "source": "cg-window",
                "window_number": 456,
            }
            if missing_focus_generation and name == "chat-send-stream":
                capture = step["capture"]
                del capture["focus_generation"]
        steps.append(step)

    if linked_screenshot_inside:
        screenshot = evidence / f"{REQUIRED_STEPS.index('chat-send-stream')}-chat-send-stream.png"
        target = evidence / "linked-chat-send-stream.png"
        _ = screenshot.replace(target)
        screenshot.symlink_to(target.name)

    bridge_executable = (
        f"{helper.resolve()}-suffix"
        if invalid_bridge_identity
        else str(helper.resolve())
    )
    receipts: dict[str, JSONValue] = {
        "events": [
            f"bridge-started kind=owned executable={bridge_executable} "
            + f"owner_sha256={'a' * 64}",
        ],
        "origin": "mounted-dmg" if forged_mounted_origin else "built-app",
        "schema": 2,
        "steps": steps,
    }
    if forged_mounted_origin:
        receipts["origin_image"] = str(root / "forged.dmg")
        receipts["origin_mount"] = str(root / "dist")
    probe: dict[str, JSONValue] = {
        "artifact_paths": {
            "browser_architecture": helper.parent.name,
            "browser_available": True,
            "browser_runtime": str(browser.resolve()),
            "helper_architecture": helper.parent.name,
            "probe": str((evidence / "provider-probe.json").resolve()),
            "runtime_executable": str(helper.resolve()),
        },
        "cwd": str(workspace.resolve()),
        "home": str((workspace.parent / "empty-home").resolve()),
        "model": "default",
        "provider": "codex-cli",
        "route": "cli",
        "search_path": (
            f"{workspace}/bin:{SANITIZED_SEARCH_PATH}"
            if unsafe_search_path
            else SANITIZED_SEARCH_PATH
        ),
        "status": "pass",
    }
    receipt_path = evidence / "packaged-journey-receipts.json"
    probe_path = evidence / "provider-probe.json"
    _ = receipt_path.write_text(
        json.dumps(receipts),
        encoding="utf-8",
    )
    _ = probe_path.write_text(
        json.dumps(probe),
        encoding="utf-8",
    )
    if linked_receipt_outside:
        outside_receipt = root / "outside-receipt.json"
        _ = receipt_path.replace(outside_receipt)
        receipt_path.symlink_to(outside_receipt)
    if linked_probe_outside:
        outside_probe = root / "outside-probe.json"
        _ = probe_path.replace(outside_probe)
        probe_path.symlink_to(outside_probe)
    return evidence, helper, workspace


def test_verifier_accepts_complete_schema_two_fixture(tmp_path: Path) -> None:
    result = _run(*_write_fixture(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "provider=codex-cli model=default route=cli" in result.stdout


def test_mounted_cache_identity_accepts_private_tree_and_rejects_root_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    verifier = importlib.import_module(
        "scripts.native.verify_packaged_journey"
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    helper = (
        tmp_path
        / "dist/Birkin.app/Contents/Helpers/arm64/birkin-native-bridge"
    )
    helper.parent.mkdir(parents=True)
    _ = helper.write_text("helper", encoding="utf-8")
    payload = b"browser"
    digest = hashlib.sha256(
        f"{hashlib.sha256(payload).hexdigest()}  ./chrome\n".encode()
    ).hexdigest()
    manifest = helper.parents[2] / "Resources/bridge-helper.json"
    manifest.parent.mkdir(parents=True)
    _ = manifest.write_text(json.dumps({
        "browser_runtimes": [{
            "architecture": "arm64",
            "path": "BrowserRuntimes/arm64",
            "sha256": digest,
            "size_bytes": len(payload),
        }],
    }), encoding="utf-8")
    cache = (
        tmp_path
        / f"home/browser-runtime-cache/arm64-{digest}"
    )
    cache.mkdir(mode=0o700, parents=True)
    _ = (cache / "chrome").write_bytes(payload)

    selected, selected_digest, selected_size = (
        verifier._mounted_browser_cache(helper, workspace)
    )

    assert selected == cache
    assert selected_digest == digest
    assert selected_size == len(payload)
    verifier._verify_browser_cache(
        selected,
        selected_digest,
        selected_size,
    )

    cache_target = tmp_path / "cache-target"
    cache.rename(cache_target)
    cache.symlink_to(cache_target, target_is_directory=True)
    with pytest.raises(verifier.JourneyVerificationError):
        _ = verifier._mounted_browser_cache(helper, workspace)


def test_verifier_accepts_producer_receipt_contract(tmp_path: Path) -> None:
    evidence, helper, workspace = _write_fixture(tmp_path)
    receipt_path = evidence / "packaged-journey-receipts.json"
    receipts = cast(
        dict[str, JSONValue],
        json.loads(receipt_path.read_text(encoding="utf-8")),
    )
    raw_steps = receipts["steps"]
    assert isinstance(raw_steps, list)
    for raw_step in cast(list[JSONValue], raw_steps):
        assert isinstance(raw_step, dict)
        step = cast(dict[str, JSONValue], raw_step)
        name = step["name"]
        assert isinstance(name, str)
        step["detail"] = name
        if name == "chat-send-stream":
            step["detail"] += (
                " provider_completion=PACKAGED_PROVIDER_COMPLETION_OK"
            )
        if name == "browser-navigate-live":
            step["detail"] += " 한국어 日本語 漢字"
    _ = receipt_path.write_text(json.dumps(receipts), encoding="utf-8")

    result = _run(evidence, helper, workspace)

    assert result.returncode == 0, result.stderr


def test_verifier_rejects_missing_arguments() -> None:
    result = _run()

    assert result.returncode == 2
    assert "usage: verify_packaged_journey.py" in result.stderr


def test_verifier_help_exits_successfully() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "usage: verify_packaged_journey.py" in result.stdout
    assert result.stderr == ""


@pytest.mark.skipif(
    os.name == "nt",
    reason="packaged launcher Python path is a macOS contract",
)
def test_verifier_loads_under_packaged_launcher_python() -> None:
    result = subprocess.run(
        ["/usr/bin/python3", str(SCRIPT)],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert result.returncode == 2
    assert "usage: verify_packaged_journey.py" in result.stderr


def test_verifier_rejects_screenshot_outside_evidence(tmp_path: Path) -> None:
    result = _run(*_write_fixture(tmp_path, escaping_screenshot=True))

    assert result.returncode == 1
    assert "screenshot must stay within evidence root" in result.stderr


def test_verifier_requires_positive_focus_generation(tmp_path: Path) -> None:
    result = _run(*_write_fixture(tmp_path, missing_focus_generation=True))

    assert result.returncode == 1
    assert "focus_generation must be an integer" in result.stderr


def test_verifier_requires_every_named_journey_capture(tmp_path: Path) -> None:
    result = _run(
        *_write_fixture(tmp_path, missing_noncritical_screenshot=True)
    )

    assert result.returncode == 1
    assert f"journey step has no screenshot: {NONCRITICAL_STEP}" in result.stderr


def test_verifier_requires_pixel_derived_cjk_markers(tmp_path: Path) -> None:
    result = _run(*_write_fixture(tmp_path, missing_cjk_ocr_markers=True))

    assert result.returncode == 1
    assert "rendered CJK markers are missing" in result.stderr


def test_verifier_requires_exact_bridge_identity(tmp_path: Path) -> None:
    result = _run(*_write_fixture(tmp_path, invalid_bridge_identity=True))

    assert result.returncode == 1
    assert "app did not launch its embedded helper" in result.stderr


def test_verifier_rejects_modified_screenshot_bytes(tmp_path: Path) -> None:
    evidence, helper, workspace = _write_fixture(tmp_path / "tampered")
    screenshot = next(evidence.glob("*-chat-send-stream.png"))
    _ = screenshot.write_bytes(_png_bytes(250))
    tampered = _run(evidence, helper, workspace)
    non_png = _run(*_write_fixture(tmp_path / "non-png", invalid_png=True))
    assert tampered.returncode == 1
    assert "screenshot digest mismatch" in tampered.stderr
    assert non_png.returncode == 1
    assert "screenshot is not PNG" in non_png.stderr


def test_verifier_rejects_internal_screenshot_symlink(tmp_path: Path) -> None:
    result = _run(*_write_fixture(tmp_path, linked_screenshot_inside=True))

    assert result.returncode == 1
    assert "screenshot must be a regular file without symlinks" in result.stderr


def test_verifier_rejects_metadata_symlinks(tmp_path: Path) -> None:
    receipt = _run(*_write_fixture(tmp_path / "receipt", linked_receipt_outside=True))
    probe = _run(*_write_fixture(tmp_path / "probe", linked_probe_outside=True))
    assert receipt.returncode == 1
    assert "receipt must be a regular file without symlinks" in receipt.stderr
    assert probe.returncode == 1
    assert "provider probe must be a regular file without symlinks" in probe.stderr


def test_verifier_rejects_symlinked_evidence_root(tmp_path: Path) -> None:
    evidence, helper, workspace = _write_fixture(tmp_path / "real")
    linked = tmp_path / "linked-evidence"
    linked.symlink_to(evidence, target_is_directory=True)

    result = _run(linked, helper, workspace)

    assert result.returncode == 1
    assert "evidence root must be a directory without symlinks" in result.stderr


def test_verifier_rejects_symlinked_evidence_ancestor(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-parent"
    evidence, helper, workspace = _write_fixture(real_parent)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    result = _run(linked_parent / evidence.name, helper, workspace)

    assert result.returncode == 1
    assert "evidence root must be a directory without symlinks" in result.stderr


def test_verifier_requires_sanitized_provider_search_path(tmp_path: Path) -> None:
    result = _run(*_write_fixture(tmp_path, unsafe_search_path=True))

    assert result.returncode == 1
    assert "provider probe search path was not sanitized" in result.stderr


def test_verifier_rejects_forged_mounted_dmg_provenance(
    tmp_path: Path,
) -> None:
    result = _run(*_write_fixture(tmp_path, forged_mounted_origin=True))

    assert result.returncode == 1
    assert "mounted-dmg journey has no attached disk image provenance" in result.stderr
