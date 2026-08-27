"""Atomic JSON records shared by Office side-effect journals."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from pathlib import Path

from .errors import DocumentError, DocumentErrorCode
from .path_security import directory_identity, sync_directory


def _error(stage: str, message: str, *, retryable: bool = False) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.PRECONDITION_FAILED,
        stage,
        message,
        retryable=retryable,
    )


def journal_root(path: Path, stage: str) -> Path:
    """Create a POSIX owner-only journal root and durably bind its entry.

    Windows relies on the directory's inherited ACL.
    """
    root = Path(path)
    existed = root.exists()
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise _error(stage, "journal root must be a real directory")
        os.chmod(root, 0o700)
        if not existed:
            sync_directory(root.parent, directory_identity(root.parent))
    except OSError as exc:
        raise _error(stage, "journal root is unavailable", retryable=True) from exc
    return root


def read_record(path: Path, stage: str) -> dict[str, object] | None:
    """Parse one complete journal record without accepting malformed fallback."""
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise _error(stage, "journal record must be a regular file")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _error(stage, "journal record is malformed") from exc
    except OSError as exc:
        raise _error(stage, "journal record is unavailable", retryable=True) from exc
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise _error(stage, "journal record must be an object")
    return {key: item for key, item in raw.items() if isinstance(key, str)}


def write_record(path: Path, record: Mapping[str, object], stage: str) -> None:
    """Atomically replace and sync a POSIX owner-only journal record.

    Windows relies on the directory's inherited ACL.
    """
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(
        dict(record),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    try:
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            _ = handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        sync_directory(path.parent, directory_identity(path.parent))
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise _error(stage, "journal record could not be persisted", retryable=True) from exc
