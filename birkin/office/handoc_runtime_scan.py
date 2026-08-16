"""Pinned-file and module-tree verification for HanDoc runtimes."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol, cast

from . import windows_native

_CHUNK_SIZE = 1024 * 1024
_MAX_MANIFEST_BYTES = 1024 * 1024


class RuntimeIdentityError(Exception):
    """The configured runtime could not be reproduced from approved bytes."""


class _Digest(Protocol):
    def update(self, value: bytes, /) -> None: ...


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _configured_path(value: object, *, directory: bool = False) -> Path:
    if not isinstance(value, str):
        raise RuntimeIdentityError
    path = Path(value)
    try:
        valid = (
            path.is_absolute()
            and path.resolve() == path
            and not path.is_symlink()
            and (path.is_dir() if directory else path.is_file())
        )
    except OSError as exc:
        raise RuntimeIdentityError from exc
    if not valid:
        raise RuntimeIdentityError
    return path


def open_runtime_file(path: Path) -> int:
    try:
        if os.name == "nt":
            native = windows_native.api()
            handle = windows_native.open_handle(
                path,
                directory=False,
                access=native.GENERIC_READ,
                share=native.FILE_SHARE_READ,
            )
            return windows_native.descriptor(handle)
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        current = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            current.st_dev,
            current.st_ino,
        ):
            os.close(descriptor)
            raise RuntimeIdentityError
        return descriptor
    except RuntimeIdentityError:
        raise
    except OSError as exc:
        raise RuntimeIdentityError from exc


def _consume_file(
    source: Path,
    target: Path | None,
    tree_digest: _Digest | None = None,
) -> tuple[str, bytes | None]:
    descriptor = open_runtime_file(source)
    digest = hashlib.sha256()
    capture = bytearray() if source.name == "package.json" else None
    output: BinaryIO | None = None
    try:
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            output = target.open("xb")
        while chunk := os.read(descriptor, _CHUNK_SIZE):
            digest.update(chunk)
            if tree_digest is not None:
                tree_digest.update(chunk)
            if capture is not None:
                if len(capture) + len(chunk) > _MAX_MANIFEST_BYTES:
                    raise RuntimeIdentityError
                capture.extend(chunk)
            if output is not None:
                _ = output.write(chunk)
    except OSError as exc:
        raise RuntimeIdentityError from exc
    finally:
        if output is not None:
            output.close()
        os.close(descriptor)
    return digest.hexdigest(), None if capture is None else bytes(capture)


def _relative_tool(name: object) -> PurePosixPath:
    if not isinstance(name, str) or not name or "\\" in name:
        raise RuntimeIdentityError
    relative = PurePosixPath(name)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise RuntimeIdentityError
    return relative


def _manifest_valid(
    content: bytes | None,
    expected: object,
    required_packages: Mapping[str, str],
) -> bool:
    if content is None or not _valid_digest(expected):
        return False
    if hashlib.sha256(content).hexdigest() != expected:
        return False
    try:
        parsed_value = cast(object, json.loads(content.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(parsed_value, dict):
        return False
    parsed = cast("dict[object, object]", parsed_value)
    dependencies_value = parsed.get("dependencies")
    if not isinstance(dependencies_value, dict):
        return False
    dependencies = cast("dict[object, object]", dependencies_value)
    return all(
        dependencies.get(name) == version for name, version in required_packages.items()
    )


def scan_modules(
    config: Mapping[str, object],
    destination: Path | None,
    required_packages: Mapping[str, str],
) -> tuple[Path, dict[str, Path], list[Path]]:
    root = _configured_path(config.get("module_root"), directory=True)
    target_root = root if destination is None else destination / "modules"
    if destination is not None:
        target_root.mkdir()
    tree_digest = hashlib.sha256()
    file_hashes: dict[str, str] = {}
    copied_files: list[Path] = []
    manifest: bytes | None = None
    try:
        paths = sorted(root.rglob("*"))
    except OSError as exc:
        raise RuntimeIdentityError from exc
    for path in paths:
        if path.is_symlink():
            raise RuntimeIdentityError
        relative = path.relative_to(root)
        target = None if destination is None else target_root / relative
        if path.is_dir():
            if target is not None:
                target.mkdir(parents=True, exist_ok=True)
            continue
        if not path.is_file():
            raise RuntimeIdentityError
        name = relative.as_posix()
        tree_digest.update(name.encode("utf-8"))
        tree_digest.update(b"\0")
        file_digest, content = _consume_file(path, target, tree_digest)
        tree_digest.update(b"\0")
        file_hashes[name] = file_digest
        if target is not None:
            copied_files.append(target)
        if name == "package.json":
            manifest = content
    if tree_digest.hexdigest() != config.get("module_tree_sha256"):
        raise RuntimeIdentityError
    if not _manifest_valid(
        manifest, config.get("package_manifest_sha256"), required_packages
    ):
        raise RuntimeIdentityError
    identities = config.get("tool_sha256")
    if not isinstance(identities, dict) or not identities:
        raise RuntimeIdentityError
    tools: dict[str, Path] = {}
    for raw_name, expected in cast("dict[object, object]", identities).items():
        relative = _relative_tool(raw_name)
        name = relative.as_posix()
        if not _valid_digest(expected) or file_hashes.get(name) != expected:
            raise RuntimeIdentityError
        tools[cast(str, raw_name)] = target_root.joinpath(*relative.parts)
    return target_root, tools, copied_files


def copy_pinned(
    config: Mapping[str, object],
    path_key: str,
    hash_key: str,
    destination: Path | None,
) -> Path:
    source = _configured_path(config.get(path_key))
    expected = config.get(hash_key)
    if not _valid_digest(expected):
        raise RuntimeIdentityError
    target = source if destination is None else destination / f"{path_key}{source.suffix}"
    digest, _ = _consume_file(source, None if destination is None else target)
    if digest != expected:
        raise RuntimeIdentityError
    return target
