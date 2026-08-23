"""Race-resistant reads for packaged journey evidence."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import NamedTuple

REQUIRED_JOURNEY_STEPS = frozenset({
    "connected", "session-create", "chat-send-stream",
    "terminal-approval-requested", "terminal-approval-approved",
    "terminal-create-lease", "terminal-input-output", "activity-receipts",
    "terminal-replay-refusal", "browser-start-live", "browser-navigate-live",
    "office-create-live", "office-open-live", "computer-use-status",
    "jailed-import-chip", "owned-bridge-restart-replay", "post-reconnect-command",
})
CRITICAL_JOURNEY_STEPS = frozenset({
    "chat-send-stream", "terminal-input-output", "jailed-import-chip",
})


class EvidenceOpenError(Exception):
    pass


class EvidenceFile(NamedTuple):
    path: Path
    data: bytes


def absolute_path(path: Path) -> Path:
    """Make a path absolute without following any symlink component."""
    return Path(os.path.abspath(path))


def _open_directory(path: Path, label: str) -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    absolute = absolute_path(path)
    descriptor = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
    except OSError as error:
        os.close(descriptor)
        raise EvidenceOpenError(
            f"{label} must be a directory without symlinks"
        ) from error
    return descriptor


def verify_png_digest(data: bytes, receipt_digest: str, label: str) -> str:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise EvidenceOpenError(f"{label} screenshot is not PNG")
    if len(receipt_digest) != 64 or any(
        character not in "0123456789abcdef" for character in receipt_digest
    ):
        raise EvidenceOpenError(f"{label} has invalid screenshot digest")
    import hashlib

    digest = hashlib.sha256(data).hexdigest()
    if digest != receipt_digest:
        raise EvidenceOpenError(f"{label} screenshot digest mismatch")
    return digest


def read_evidence_file(
    evidence_root: Path,
    value: str,
    label: str,
) -> EvidenceFile:
    root = absolute_path(evidence_root)
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            relative = absolute_path(candidate).relative_to(root)
        except ValueError as error:
            raise EvidenceOpenError(
                f"{label} must stay within evidence root: {candidate}"
            ) from error
    else:
        relative = candidate
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise EvidenceOpenError(
            f"{label} must stay within evidence root: {candidate}"
        )
    flags = os.O_RDONLY | os.O_CLOEXEC
    root_fd = _open_directory(root, "evidence root")
    directory_fd = root_fd
    try:
        for component in relative.parts[:-1]:
            next_fd = os.open(
                component,
                flags | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            if directory_fd != root_fd:
                os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            relative.parts[-1],
            flags | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )
        try:
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise EvidenceOpenError(
                    f"{label} must be a regular file without symlinks"
                )
            with os.fdopen(file_fd, "rb", closefd=False) as handle:
                data = handle.read()
        finally:
            os.close(file_fd)
    except OSError as error:
        raise EvidenceOpenError(
            f"{label} must be a regular file without symlinks"
        ) from error
    finally:
        if directory_fd != root_fd:
            os.close(directory_fd)
        os.close(root_fd)
    return EvidenceFile(path=root / relative, data=data)
