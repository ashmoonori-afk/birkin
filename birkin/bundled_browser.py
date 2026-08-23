"""Integrity gate for browser runtimes shipped with a frozen macOS helper."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import cast

from birkin import __version__
from birkin.bundled_browser_cache import (
    RuntimeCacheError,
    select_browser_runtime,
)


class BundledBrowserErrorCode(Enum):
    MANIFEST_MISSING = "bundled_browser_manifest_missing"
    MANIFEST_INVALID = "bundled_browser_manifest_invalid"
    ARCHITECTURE_MISSING = "bundled_browser_architecture_missing"
    RUNTIME_MISSING = "bundled_browser_runtime_missing"
    INTEGRITY_FAILED = "bundled_browser_integrity_failed"


_MESSAGES = {
    BundledBrowserErrorCode.MANIFEST_MISSING:
        "The bundled browser manifest is missing. Reinstall Birkin.",
    BundledBrowserErrorCode.MANIFEST_INVALID:
        "The bundled browser manifest is invalid. Reinstall Birkin.",
    BundledBrowserErrorCode.ARCHITECTURE_MISSING:
        "No bundled browser supports this Mac architecture. Reinstall Birkin.",
    BundledBrowserErrorCode.RUNTIME_MISSING:
        "The bundled browser runtime is missing. Reinstall Birkin.",
    BundledBrowserErrorCode.INTEGRITY_FAILED:
        "The bundled browser runtime failed its integrity check. Reinstall Birkin.",
}


class BundledBrowserRuntimeError(RuntimeError):
    def __init__(self, code: BundledBrowserErrorCode) -> None:
        self.code = code
        super().__init__(_MESSAGES[code])


@dataclass(frozen=True, slots=True)
class BrowserRuntimeRecord:
    architecture: str
    path: str
    sha256: str
    size_bytes: int
    playwright_version: str
    chromium_revision: str
    ffmpeg_revision: str
    headless_executable: str
    ffmpeg_executable: str

    @classmethod
    def parse(cls, value: object) -> BrowserRuntimeRecord:
        expected = {
            "architecture", "path", "sha256", "size_bytes",
            "playwright_version", "chromium_revision", "ffmpeg_revision",
            "headless_executable", "ffmpeg_executable",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("invalid browser runtime record")
        strings = {key: item for key, item in value.items() if key != "size_bytes"}
        size = value["size_bytes"]
        if (len(strings) != len(expected) - 1
                or not all(isinstance(item, str) for item in strings.values())
                or not isinstance(size, int) or isinstance(size, bool) or size <= 0):
            raise ValueError("invalid browser runtime field")
        return cls(size_bytes=size, **cast(dict[str, str], strings))


def ensure_bundled_browser(
    *,
    executable: Path | None = None,
    frozen: bool | None = None,
) -> Path | None:
    """Select and verify only the browser sealed beside a frozen helper."""
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not is_frozen:
        return None
    os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    helper = (executable or Path(sys.executable)).resolve()
    if helper.parent.parent.name != "Helpers" or helper.parents[2].name != "Contents":
        raise BundledBrowserRuntimeError(BundledBrowserErrorCode.MANIFEST_MISSING)
    architecture = helper.parent.name
    resources = helper.parents[2] / "Resources"
    manifest_path = resources / "bridge-helper.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise BundledBrowserRuntimeError(BundledBrowserErrorCode.MANIFEST_MISSING)
    try:
        payload = cast(object, json.loads(manifest_path.read_text(encoding="utf-8")))
        if not isinstance(payload, dict) or payload.get("package_version") != __version__:
            raise ValueError
        records = payload["browser_runtimes"]
        if not isinstance(records, list):
            raise ValueError
        selected = [item for item in records if isinstance(item, dict)
                    and item.get("architecture") == architecture]
        if len(selected) != 1:
            raise BundledBrowserRuntimeError(
                BundledBrowserErrorCode.ARCHITECTURE_MISSING
            )
        record = BrowserRuntimeRecord.parse(selected[0])
    except BundledBrowserRuntimeError:
        raise
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise BundledBrowserRuntimeError(
            BundledBrowserErrorCode.MANIFEST_INVALID
        ) from error
    expected_path = f"BrowserRuntimes/{architecture}"
    if (record.architecture != architecture or record.path != expected_path
            or record.playwright_version != "1.62.0"
            or not record.chromium_revision.isdecimal()
            or not record.ffmpeg_revision.isdecimal()):
        raise BundledBrowserRuntimeError(BundledBrowserErrorCode.MANIFEST_INVALID)
    root = resources / record.path
    if not root.is_dir() or root.is_symlink():
        raise BundledBrowserRuntimeError(BundledBrowserErrorCode.RUNTIME_MISSING)
    _verify_runtime_root(root, record)
    try:
        selected = select_browser_runtime(
            root,
            architecture=record.architecture,
            sha256=record.sha256,
            verify=lambda candidate: _verify_runtime_root(candidate, record),
        )
    except RuntimeCacheError as error:
        raise BundledBrowserRuntimeError(
            BundledBrowserErrorCode.INTEGRITY_FAILED
        ) from error
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(selected)
    return selected


def _verify_runtime_root(
    root: Path,
    record: BrowserRuntimeRecord,
) -> None:
    if not root.is_dir() or root.is_symlink():
        raise BundledBrowserRuntimeError(
            BundledBrowserErrorCode.INTEGRITY_FAILED
        )
    digest, size = browser_tree_identity(root)
    if digest != record.sha256 or size != record.size_bytes:
        raise BundledBrowserRuntimeError(
            BundledBrowserErrorCode.INTEGRITY_FAILED
        )
    for relative in (record.headless_executable, record.ffmpeg_executable):
        candidate = root / relative
        if (
            not candidate.is_file()
            or candidate.is_symlink()
            or not os.access(candidate, os.X_OK)
        ):
            raise BundledBrowserRuntimeError(
                BundledBrowserErrorCode.INTEGRITY_FAILED
            )


def browser_tree_identity(root: Path) -> tuple[str, int]:
    tree = hashlib.sha256()
    size = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise BundledBrowserRuntimeError(BundledBrowserErrorCode.INTEGRITY_FAILED)
        if path.is_dir():
            continue
        if not path.is_file():
            raise BundledBrowserRuntimeError(BundledBrowserErrorCode.INTEGRITY_FAILED)
        relative = "./" + path.relative_to(root).as_posix()
        file_hash = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                file_hash.update(chunk)
        tree.update(f"{file_hash.hexdigest()}  {relative}\n".encode())
        size += path.stat().st_size
    return tree.hexdigest(), size


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    digest, size = browser_tree_identity(args.root)
    print(json.dumps(
        {"sha256": digest, "size_bytes": size},
        sort_keys=True,
        separators=(",", ":"),
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
