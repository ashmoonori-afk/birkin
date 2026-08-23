#!/usr/bin/env python3
"""Verify machine evidence emitted by the production packaged journey."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import stat
import sys
from pathlib import Path
from typing import Protocol, cast

from packaged_evidence_io import (
    CRITICAL_JOURNEY_STEPS,
    EvidenceOpenError,
    REQUIRED_JOURNEY_STEPS,
    absolute_path,
    read_evidence_file,
    verify_png_digest,
)


class JSONValue(Protocol):
    pass


JSONObject = dict[str, JSONValue]
SANITIZED_PROVIDER_SEARCH_PATH = (
    "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
)
CJK_SPECIMENS = frozenset(("한국어", "日本語", "漢字"))


class JourneyVerificationError(Exception):
    pass


def _object(value: JSONValue, label: str) -> JSONObject:
    if not isinstance(value, dict):
        raise JourneyVerificationError(f"{label} must be an object")
    return cast(JSONObject, value)


def _objects(value: JSONValue, label: str) -> list[JSONObject]:
    if not isinstance(value, list):
        raise JourneyVerificationError(f"{label} must be an array")
    return [_object(item, label) for item in cast(list[JSONValue], value)]


def _string(value: JSONValue, label: str) -> str:
    if not isinstance(value, str):
        raise JourneyVerificationError(f"{label} must be a string")
    return value


def _integer(value: JSONValue, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise JourneyVerificationError(f"{label} must be an integer")
    return value


def _load(data: bytes, label: str) -> JSONObject:
    raw = cast(JSONValue, json.loads(data))
    return _object(raw, label)


def _attached_disk_images() -> set[tuple[Path, Path]]:
    if sys.platform != "darwin":
        return set()
    read_descriptor, write_descriptor = os.pipe()
    try:
        process = os.posix_spawn(
            "/usr/bin/hdiutil",
            ["/usr/bin/hdiutil", "info", "-plist"],
            {},
            file_actions=[
                (os.POSIX_SPAWN_DUP2, write_descriptor, 1),
                (os.POSIX_SPAWN_CLOSE, read_descriptor),
                (os.POSIX_SPAWN_CLOSE, write_descriptor),
            ],
        )
    except OSError:
        os.close(read_descriptor)
        os.close(write_descriptor)
        return set()
    os.close(write_descriptor)
    try:
        with os.fdopen(read_descriptor, "rb") as output:
            encoded = output.read()
        _, status = os.waitpid(process, 0)
        if os.waitstatus_to_exitcode(status) != 0:
            return set()
        payload = _object(
            cast(JSONValue, plistlib.loads(encoded)),
            "hdiutil info",
        )
    except (OSError, plistlib.InvalidFileException):
        return set()
    images: set[tuple[Path, Path]] = set()
    images_value = payload.get("images")
    if not isinstance(images_value, list):
        return images
    for value in cast(list[JSONValue], images_value):
        if not isinstance(value, dict):
            continue
        image = cast(JSONObject, value)
        if image.get("writeable") is not False:
            continue
        image_path = image.get("image-path")
        if not isinstance(image_path, str) or not image_path:
            continue
        entities_value = image.get("system-entities")
        if not isinstance(entities_value, list):
            continue
        for entity_value in cast(list[JSONValue], entities_value):
            if not isinstance(entity_value, dict):
                continue
            entity = cast(JSONObject, entity_value)
            mount = entity.get("mount-point")
            if isinstance(mount, str) and mount:
                images.add((Path(mount).resolve(), Path(image_path).resolve()))
    return images


def _require_within(path: Path, root: Path, label: str) -> None:
    try:
        _ = path.relative_to(root)
    except ValueError as error:
        raise JourneyVerificationError(
            f"{label} did not come from mounted disk image: {path}"
        ) from error


def _mounted_browser_cache(
    helper: Path,
    workspace: Path,
) -> tuple[Path, str, int]:
    architecture = helper.parent.name
    manifest = helper.parents[2] / "Resources/bridge-helper.json"
    if not manifest.is_file() or manifest.is_symlink():
        raise JourneyVerificationError(
            "packaged browser manifest is missing or linked"
        )
    payload = _load(manifest.read_bytes(), manifest.name)
    records = _objects(payload.get("browser_runtimes"), "browser_runtimes")
    selected = [
        record for record in records
        if record.get("architecture") == architecture
    ]
    if len(selected) != 1:
        raise JourneyVerificationError(
            "packaged browser architecture is ambiguous"
        )
    record = selected[0]
    digest = _string(record.get("sha256"), "browser sha256")
    size = _integer(record.get("size_bytes"), "browser size_bytes")
    if (
        len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or record.get("path") != f"BrowserRuntimes/{architecture}"
        or size <= 0
    ):
        raise JourneyVerificationError(
            "packaged browser cache identity is invalid"
        )
    cache = (
        workspace.parent
        / "home/browser-runtime-cache"
        / f"{architecture}-{digest}"
    )
    return cache.resolve(), digest, size


def _verify_browser_cache(
    root: Path,
    expected_digest: str,
    expected_size: int,
) -> None:
    if (
        not root.is_dir()
        or root.is_symlink()
        or stat.S_IMODE(root.stat().st_mode) != 0o700
    ):
        raise JourneyVerificationError(
            "provider browser cache is not private"
        )
    tree = hashlib.sha256()
    size = 0
    for path in sorted(
        root.rglob("*"),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        if path.is_symlink():
            raise JourneyVerificationError(
                "provider browser cache contains a link"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise JourneyVerificationError(
                "provider browser cache contains a special file"
            )
        metadata = path.stat()
        if metadata.st_nlink != 1:
            raise JourneyVerificationError(
                "provider browser cache contains a hard link"
            )
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        relative = "./" + path.relative_to(root).as_posix()
        tree.update(f"{digest.hexdigest()}  {relative}\n".encode())
        size += metadata.st_size
    if tree.hexdigest() != expected_digest or size != expected_size:
        raise JourneyVerificationError(
            "provider browser cache identity changed"
        )


def verify(evidence: Path, helper: Path, workspace: Path) -> str:
    evidence = absolute_path(evidence)
    helper = helper.resolve()
    workspace = workspace.resolve()
    try:
        receipt_file = read_evidence_file(
            evidence, "packaged-journey-receipts.json", "receipt"
        )
        probe_file = read_evidence_file(
            evidence, "provider-probe.json", "provider probe"
        )
    except EvidenceOpenError as error:
        raise JourneyVerificationError(str(error)) from error
    receipts = _load(receipt_file.data, receipt_file.path.name)
    probe = _load(probe_file.data, probe_file.path.name)
    if receipts.get("schema") != 2:
        raise JourneyVerificationError(
            f"journey receipt schema is not 2: {receipts.get('schema')}"
        )
    origin = receipts.get("origin")
    if origin not in {"built-app", "mounted-dmg"}:
        raise JourneyVerificationError(f"journey origin is invalid: {origin}")
    raw_origin_mount = receipts.get("origin_mount")
    raw_origin_image = receipts.get("origin_image")
    origin_mount = (
        "" if raw_origin_mount is None
        else _string(raw_origin_mount, "origin_mount")
    )
    origin_image = (
        "" if raw_origin_image is None
        else _string(raw_origin_image, "origin_image")
    )
    mounted_root: Path | None = None
    if origin == "built-app":
        if origin_mount or origin_image:
            raise JourneyVerificationError(
                "built-app journey must not claim disk image provenance"
            )
    else:
        mounted_root = Path(origin_mount).resolve()
        image = Path(origin_image).resolve()
        if not origin_mount or not origin_image or (
            mounted_root, image
        ) not in _attached_disk_images():
            raise JourneyVerificationError(
                "mounted-dmg journey has no attached disk image provenance"
            )

    identity = tuple(
        probe.get(key) for key in ("status", "provider", "model", "route")
    )
    if identity != ("pass", "codex-cli", "default", "cli"):
        raise JourneyVerificationError(f"provider probe identity failed: {identity}")
    if Path(_string(probe.get("cwd"), "probe.cwd")).resolve() != workspace:
        raise JourneyVerificationError(
            f"provider probe cwd mismatch: {probe.get('cwd')}"
        )
    if Path(_string(probe.get("home"), "probe.home")).resolve() != (
        workspace.parent / "empty-home"
    ):
        raise JourneyVerificationError(
            f"provider probe HOME was not isolated: {probe.get('home')}"
        )
    search_path = _string(probe.get("search_path"), "probe.search_path")
    if search_path != SANITIZED_PROVIDER_SEARCH_PATH:
        raise JourneyVerificationError(
            f"provider probe search path was not sanitized: {search_path}"
        )
    artifacts = _object(probe.get("artifact_paths"), "probe.artifact_paths")
    if Path(_string(artifacts.get("runtime_executable"), "runtime_executable")).resolve() != helper:
        raise JourneyVerificationError(
            f"provider probe did not use packaged helper: {artifacts}"
        )
    expected_browser = helper.parents[2] / "Resources/BrowserRuntimes" / helper.parent.name
    expected_app = helper.parents[2] / "MacOS" / "BirkinNativeApp"
    if origin == "mounted-dmg":
        if mounted_root is None:
            raise JourneyVerificationError(
                "mounted-dmg journey has no attached disk image provenance"
            )
        _require_within(helper, mounted_root, "packaged helper")
        _require_within(expected_browser, mounted_root, "bundled browser")
        _require_within(expected_app, mounted_root, "packaged app")
    actual_browser = Path(
        _string(artifacts.get("browser_runtime"), "browser_runtime")
    ).resolve()
    if origin == "mounted-dmg":
        cache, digest, size = _mounted_browser_cache(helper, workspace)
        if actual_browser != cache:
            raise JourneyVerificationError(
                f"provider probe did not verify private browser cache: {artifacts}"
            )
        _verify_browser_cache(cache, digest, size)
    elif actual_browser != expected_browser:
        raise JourneyVerificationError(
            f"provider probe did not verify bundled browser: {artifacts}"
        )
    if Path(_string(artifacts.get("probe"), "probe artifact")) != probe_file.path:
        raise JourneyVerificationError(
            f"provider probe artifact mismatch: {artifacts}"
        )

    events_value = receipts.get("events")
    if not isinstance(events_value, list):
        raise JourneyVerificationError("journey events must be strings")
    events = [
        _string(item, "journey event")
        for item in cast(list[JSONValue], events_value)
    ]
    bridge_starts = [
        event for event in events if event.startswith("bridge-started kind=owned ")
    ]
    if len(bridge_starts) != 1:
        raise JourneyVerificationError(
            f"app did not launch its embedded helper: {bridge_starts}"
        )
    _, separator, bridge_identity = bridge_starts[0].rpartition(" executable=")
    bridge_executable, owner_separator, owner_digest = bridge_identity.partition(
        " owner_sha256="
    )
    if (
        not separator
        or not owner_separator
        or len(owner_digest) != 64
        or any(character not in "0123456789abcdef" for character in owner_digest)
        or Path(bridge_executable).resolve() != helper
    ):
        raise JourneyVerificationError(
            f"app did not launch its embedded helper: {bridge_starts}"
        )

    steps = _objects(receipts.get("steps"), "steps")
    names = {_string(step.get("name"), "step.name") for step in steps}
    if missing := REQUIRED_JOURNEY_STEPS - names:
        raise JourneyVerificationError(f"missing journey steps: {sorted(missing)}")
    failed = [
        _string(step.get("name"), "step.name")
        for step in steps if step.get("succeeded") is not True
    ]
    if failed:
        raise JourneyVerificationError(f"failed journey steps: {failed}")
    by_name = {_string(step.get("name"), "step.name"): step for step in steps}
    if "provider_completion=PACKAGED_PROVIDER_COMPLETION_OK" not in _string(
        by_name["chat-send-stream"].get("detail"), "chat detail"
    ):
        raise JourneyVerificationError(
            "chat step has no successful provider completion"
        )
    encoded = json.dumps(receipts, sort_keys=True).lower()
    for forbidden in (
        "401 unauthorized", "refresh_token_reused", "codex produced no message",
        "the native packaged app is connected to python authority",
    ):
        if forbidden in encoded:
            raise JourneyVerificationError(
                f"non-provider chat evidence survived: {forbidden}"
            )
    if not names.intersection(("working-memory-clear", "working-memory-gated")):
        raise JourneyVerificationError("no Working Memory step was recorded")
    detail_text = "\n".join(
        _string(step.get("detail"), "step.detail") for step in steps
    )
    for specimen in ("한국어", "日本語", "漢字"):
        if specimen not in detail_text:
            raise JourneyVerificationError(
                f"journey CJK specimen is missing: {specimen}"
            )

    digests: dict[str, str] = {}
    critical_digests: dict[str, str] = {}
    owner_pids: set[int] = set()
    window_numbers: set[int] = set()
    rendered_cjk: set[str] = set()
    last_focus_generation = 0
    for step in steps:
        name = _string(step.get("name"), "step.name")
        shot = _string(step.get("screenshot"), "step.screenshot")
        if not shot:
            raise JourneyVerificationError(
                f"journey step has no screenshot: {name}"
            )
        capture = _object(step.get("capture"), f"{name}.capture")
        if capture.get("source") != "cg-window":
            raise JourneyVerificationError(
                f"{name} used a synthetic capture source"
            )
        if capture.get("focus_target") != step.get("surface"):
            raise JourneyVerificationError(
                f"{name} focus target does not match its surface"
            )
        focus_generation = _integer(
            capture.get("focus_generation"),
            "focus_generation",
        )
        if focus_generation <= last_focus_generation:
            raise JourneyVerificationError(
                f"{name} focus generation did not advance"
            )
        last_focus_generation = focus_generation
        owner_pids.add(_integer(capture.get("owner_pid"), "owner_pid"))
        window_numbers.add(_integer(capture.get("window_number"), "window_number"))
        point_width = _integer(capture.get("point_width"), "point_width")
        point_height = _integer(capture.get("point_height"), "point_height")
        pixel_width = _integer(capture.get("pixel_width"), "pixel_width")
        pixel_height = _integer(capture.get("pixel_height"), "pixel_height")
        if point_width < 960 or point_height < 640:
            raise JourneyVerificationError(
                f"{name} captured undersized window bounds"
            )
        if pixel_width < point_width or pixel_height < point_height:
            raise JourneyVerificationError(
                f"{name} captured invalid pixel dimensions"
            )
        executable = Path(
            _string(capture.get("executable_path"), "executable_path")
        ).resolve()
        if executable != expected_app:
            raise JourneyVerificationError(f"{name} captured the wrong executable")
        try:
            screenshot_file = read_evidence_file(evidence, shot, "screenshot")
        except EvidenceOpenError as error:
            raise JourneyVerificationError(str(error)) from error
        data = screenshot_file.data
        receipt_digest = _string(capture.get("png_sha256"), "png_sha256")
        marker_value = capture.get("cjk_ocr_markers")
        if not isinstance(marker_value, list):
            raise JourneyVerificationError(
                f"{name} CJK OCR markers must be an array"
            )
        markers = {
            _string(marker, "cjk_ocr_marker")
            for marker in cast(list[JSONValue], marker_value)
        }
        if unexpected := markers - CJK_SPECIMENS:
            raise JourneyVerificationError(
                f"{name} has unexpected CJK OCR markers: {sorted(unexpected)}"
            )
        rendered_cjk.update(markers)
        try:
            digest = verify_png_digest(data, receipt_digest, shot)
        except EvidenceOpenError as error:
            raise JourneyVerificationError(str(error)) from error
        if len(data) < 4_000:
            raise JourneyVerificationError(
                f"{shot} is not a contentful screenshot"
            )
        if previous := digests.get(digest):
            raise JourneyVerificationError(
                f"journey state screenshots are byte-identical: {previous} and {shot}"
            )
        digests[digest] = shot
        if name in CRITICAL_JOURNEY_STEPS:
            critical_digests[name] = digest
    if set(critical_digests) != set(CRITICAL_JOURNEY_STEPS):
        raise JourneyVerificationError(
            f"missing critical screenshot digests: {critical_digests}"
        )
    if missing_cjk := CJK_SPECIMENS - rendered_cjk:
        raise JourneyVerificationError(
            f"rendered CJK markers are missing: {sorted(missing_cjk)}"
        )
    if len(owner_pids) != 1 or 0 in owner_pids:
        raise JourneyVerificationError(
            f"journey captures changed owner PID: {owner_pids}"
        )
    if len(window_numbers) != 1 or 0 in window_numbers:
        raise JourneyVerificationError(
            f"journey captures changed window identity: {window_numbers}"
        )
    return (
        f"provider={probe['provider']} model={probe['model']} route={probe['route']} "
        f"cwd={probe['cwd']} artifacts={artifacts} journey_steps={len(steps)} "
        f"screenshots={len(digests)} distinct_screenshots={len(digests)}"
    )


def main() -> int:
    usage = "usage: verify_packaged_journey.py EVIDENCE HELPER WORKSPACE"
    if len(sys.argv) == 2 and sys.argv[1] in {"-h", "--help"}:
        print(usage)
        return 0
    if len(sys.argv) != 4:
        print(usage, file=sys.stderr)
        return 2
    try:
        print(verify(*(Path(value) for value in sys.argv[1:])))
    except (JourneyVerificationError, KeyError, OSError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
