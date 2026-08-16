"""Platform primitives for immutable artifact snapshot handles."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from . import windows_native
from .errors import DocumentError, DocumentErrorCode
from .path_identity import descriptor_identity


def protect_snapshot(
    path: Path,
    descriptor: int,
    *,
    platform: str | None = None,
) -> None:
    """Make a completed snapshot read-only with native-safe primitives."""
    selected = os.name if platform is None else platform
    if selected == "nt":
        os.chmod(path, 0o400)
        return
    os.fchmod(descriptor, 0o400)
    if hasattr(os, "chflags"):
        os.chflags(path, stat.UF_IMMUTABLE)


def sync_read_descriptor(descriptor: int, *, platform: str | None = None) -> None:
    """Flush read descriptors where the platform supports that operation."""
    if (os.name if platform is None else platform) != "nt":
        os.fsync(descriptor)


def prepare_snapshot_cleanup(path: Path) -> None:
    if hasattr(os, "chflags"):
        try:
            os.chflags(path, 0)
        except OSError:
            pass
    if os.name == "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def replace_with_windows_snapshot_guard(descriptor: int, path: Path) -> int:
    """Replace a writable descriptor with a read guard for the same identity."""
    try:
        expected = descriptor_identity(descriptor)
    finally:
        os.close(descriptor)
    guarded = windows_native.open_read_guard(path)
    try:
        if descriptor_identity(guarded) != expected:
            raise DocumentError(
                DocumentErrorCode.SOURCE_CHANGED,
                "import",
                "artifact snapshot path identity changed",
            )
        return guarded
    except BaseException:
        os.close(guarded)
        raise


def descriptor_snapshot_path(descriptor: int) -> Path:
    expected = descriptor_identity(descriptor)
    for root in (Path("/proc/self/fd"), Path("/dev/fd")):
        candidate = root / str(descriptor)
        probe = -1
        try:
            probe = os.open(candidate, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
            metadata = os.fstat(probe)
            if stat.S_ISREG(metadata.st_mode) and descriptor_identity(probe) == expected:
                return candidate
        except OSError:
            continue
        finally:
            if probe >= 0:
                os.close(probe)
    raise DocumentError(
        DocumentErrorCode.CAPABILITY_UNAVAILABLE,
        "import",
        "this platform cannot expose an identity-bound artifact descriptor",
    )
