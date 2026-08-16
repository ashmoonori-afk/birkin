"""Descriptor-based filesystem checks for the document workspace jail."""

from __future__ import annotations

import hashlib
import os
import stat
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from . import windows_native
from .errors import DocumentError, DocumentErrorCode
from .path_identity import (
    close_guard,
    descriptor_identity,
    directory_identity,
    ensure_directory_identity,
    ensure_open_identity,
    ensure_path_identity,
    guard_identity,
    open_directory_guard,
    open_identity_guard,
    open_regular_guard,
    regular_path_identity,
    sync_directory,
)
from .secure_file_open import open_regular


def canonical_name(name: str) -> str:
    """Collision key: NFC plus Unicode case folding; aliases are refused."""
    return unicodedata.normalize("NFC", name).casefold()


def hash_path(path: Path) -> str:
    descriptor = -1
    handle = -1
    try:
        if os.name == "nt":
            native = windows_native.api()
            handle = windows_native.open_handle(
                path,
                directory=False,
                access=native.GENERIC_READ,
                share=native.FILE_SHARE_READ,
            )
            descriptor = windows_native.descriptor(handle)
            handle = -1
            if descriptor_identity(descriptor) != regular_path_identity(path):
                raise OSError("path is not a stable regular file")
        else:
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
            current = os.stat(path, follow_symlinks=False)
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
                current.st_dev,
                current.st_ino,
            ):
                raise OSError("path is not a stable regular file")
        return hash_descriptor(descriptor)
    except OSError as exc:
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "import",
            "artifact is not a readable regular file",
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if handle >= 0:
            windows_native.close_handle(handle)


def hash_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    _ = os.lseek(descriptor, 0, os.SEEK_SET)
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    _ = os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest()


def enforce_content_limit(value: object, maximum: int) -> None:
    remaining = maximum
    pending: list[object] = [value]
    seen: set[int] = set()
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            remaining -= len(item)
        elif isinstance(item, Mapping):
            mapping = cast("Mapping[object, object]", item)
            identity = id(mapping)
            if identity in seen:
                raise DocumentError(
                    DocumentErrorCode.INVALID_INPUT,
                    "plan",
                    "content must not contain cycles",
                )
            seen.add(identity)
            pending.extend(mapping.keys())
            pending.extend(mapping.values())
        elif isinstance(item, (list, tuple)):
            sequence = cast("list[object] | tuple[object, ...]", item)
            identity = id(sequence)
            if identity in seen:
                raise DocumentError(
                    DocumentErrorCode.INVALID_INPUT,
                    "plan",
                    "content must not contain cycles",
                )
            seen.add(identity)
            pending.extend(sequence)
        if remaining < 0:
            raise DocumentError(
                DocumentErrorCode.LIMIT_EXCEEDED,
                "plan",
                f"document content exceeds the {maximum} character limit",
            )


__all__ = [
    "canonical_name",
    "close_guard",
    "descriptor_identity",
    "directory_identity",
    "enforce_content_limit",
    "ensure_directory_identity",
    "ensure_open_identity",
    "ensure_path_identity",
    "guard_identity",
    "hash_descriptor",
    "hash_path",
    "open_directory_guard",
    "open_identity_guard",
    "open_regular",
    "open_regular_guard",
    "regular_path_identity",
    "sync_directory",
]
