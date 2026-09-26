"""Copy one local Office file into the managed document jail.

Office tools open sources only inside ``BIRKIN_HOME/office``. This module is
the model-callable copy-in path for a file in the current workspace, a
Telegram attachment under ``BIRKIN_HOME/uploads``, or the documented drop
folder ``BIRKIN_HOME/office/artifacts/incoming``. The original file is only
ever read, and its absolute path never crosses the result boundary.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path
from typing import Final

from .adapters.catalog import supported_formats
from .errors import DocumentError, DocumentErrorCode
from .path_security import canonical_name
from .secure_file_open import open_regular
from .service import DocumentService

# The same per-file cap as the web import boundary
# (birkin.native.jailed_import.MAX_IMPORT_BYTES); a test keeps them equal
# without importing the native layer here.
MAX_IMPORT_BYTES: Final = 64 * 1024 * 1024
SUPPORTED_SUFFIXES: Final = frozenset(f".{name}" for name in supported_formats())
_MAX_STEM_BYTES: Final = 120
_CHUNK_BYTES: Final = 1024 * 1024
# Birkin-owned folders a user file may arrive in; everything else under
# BIRKIN_HOME is Birkin state and is never imported.
_BIRKIN_DROP_FOLDERS: Final = (
    ("uploads",),
    ("office", "artifacts", "incoming"),
)


def _error(
    code: DocumentErrorCode, message: str, reason: str | None = None
) -> DocumentError:
    details: dict[str, object] = {} if reason is None else {"reason": reason}
    return DocumentError(code, "import", message, details=details)


def _candidate(raw_path: object, workspace: Path) -> Path:
    if not isinstance(raw_path, str) or not raw_path or "\0" in raw_path:
        raise _error(
            DocumentErrorCode.INVALID_INPUT, "path must be a non-empty file path"
        )
    try:
        candidate = Path(raw_path).expanduser()
    except RuntimeError as exc:
        raise _error(
            DocumentErrorCode.INVALID_INPUT, "path home directory is unavailable"
        ) from exc
    return candidate if candidate.is_absolute() else workspace.resolve() / candidate


def _jailed_path(candidate: Path, workspace: Path, home: Path) -> tuple[Path, Path]:
    """Return the real root of the first matching import root and the path in it.

    Matching is purely textual, so a path outside every root is never
    touched on disk. Root identity is verified later when it is opened.
    """
    roots = [home.joinpath(*folder) for folder in _BIRKIN_DROP_FOLDERS]
    roots.append(workspace)
    for root in roots:
        try:
            real_root = root.resolve(strict=True)
        except OSError:
            continue
        for form in (root.absolute(), real_root):
            if candidate.is_relative_to(form):
                relative = candidate.relative_to(form)
                if ".." in relative.parts:
                    break
                return real_root, real_root / relative
    raise _error(
        DocumentErrorCode.PERMISSION_DENIED,
        "path is outside the workspace and the Birkin upload folders",
        "outside_import_roots",
    )


def _within(path: tuple[str, ...], root: tuple[str, ...]) -> bool:
    return path[: len(root)] == root


def _identity(path: Path, *, follow_symlinks: bool = True) -> tuple[int, int] | None:
    try:
        metadata = os.stat(path, follow_symlinks=follow_symlinks)
    except OSError:
        return None
    return metadata.st_dev, metadata.st_ino


def _is_birkin_state_by_identity(real_path: Path, home: Path) -> bool:
    # An alias the text does not match, such as a Windows 8.3 short name or
    # a macOS firmlink, still opens the same directory, so walk the parents
    # by native identity. The nearest Birkin-owned directory decides. A drop
    # folder counts only as itself, never through a redirecting link.
    home_identity = _identity(home)
    if home_identity is None:
        return False
    drops = {
        _identity(home.joinpath(*folder), follow_symlinks=False)
        for folder in _BIRKIN_DROP_FOLDERS
    }
    drops.discard(None)
    for directory in real_path.parents:
        identity = _identity(directory)
        if identity in drops:
            return False
        if identity == home_identity:
            return True
    return False


def _is_birkin_state(real_path: Path, home: Path) -> bool:
    # Compare NFC-casefolded components: on a case- or normalization-
    # insensitive volume another spelling still names the same directory.
    def key(path: Path) -> tuple[str, ...]:
        return tuple(canonical_name(part) for part in path.parts)

    if _is_birkin_state_by_identity(real_path, home):
        return True
    real_home = home.resolve()
    path = key(real_path)
    if not _within(path, key(real_home)):
        return False
    return not any(
        _within(path, key(real_home.joinpath(*folder)))
        for folder in _BIRKIN_DROP_FOLDERS
    )


def _bounded_sha256(descriptor: int) -> str:
    if os.fstat(descriptor).st_size > MAX_IMPORT_BYTES:
        raise _error(
            DocumentErrorCode.LIMIT_EXCEEDED, "source file exceeds the import byte limit"
        )
    digest = hashlib.sha256()
    total = 0
    while chunk := os.read(descriptor, _CHUNK_BYTES):
        total += len(chunk)
        if total > MAX_IMPORT_BYTES:
            raise _error(
                DocumentErrorCode.LIMIT_EXCEEDED,
                "source file exceeds the import byte limit",
            )
        digest.update(chunk)
    return digest.hexdigest()


def _safe_stem(path: Path) -> str:
    stem = unicodedata.normalize("NFC", path.stem)
    stem = re.sub(r"[^\w.-]+", "_", stem, flags=re.UNICODE).strip("._") or "document"
    encoded = stem.encode("utf-8")
    if len(encoded) > _MAX_STEM_BYTES:
        stem = encoded[:_MAX_STEM_BYTES].decode("utf-8", errors="ignore")
    return stem


def import_local_document(
    service: DocumentService,
    raw_path: object,
    *,
    workspace: Path,
    birkin_home: Path,
) -> dict[str, object]:
    """Copy one supported local Office file into managed drafts, unchanged."""
    candidate = _candidate(raw_path, workspace)
    suffix = candidate.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise _error(
            DocumentErrorCode.UNSUPPORTED_FORMAT,
            "local import supports docx, xlsx, pptx, pdf, and hwpx files",
        )
    real_root, real_path = _jailed_path(candidate, workspace, birkin_home)
    if _is_birkin_state(real_path, birkin_home):
        raise _error(
            DocumentErrorCode.PERMISSION_DENIED,
            "Birkin state files cannot be imported",
            "birkin_state",
        )
    # Walks each component with O_NOFOLLOW and checks the root identity, so
    # a symlink, "..", or non-regular file below the root is refused.
    descriptor = open_regular(real_path, real_root)
    try:
        # The state check above judges the path, not the file: a hard link
        # is a second name for a file that may live in Birkin state.
        if os.fstat(descriptor).st_nlink > 1:
            raise _error(
                DocumentErrorCode.PERMISSION_DENIED,
                "하드 링크로 연결된 파일은 가져올 수 없습니다. "
                "파일을 일반 복사본으로 만든 뒤 다시 가져오세요.",
                "hard_link",
            )
        digest = _bounded_sha256(descriptor)
        output_name = f"{_safe_stem(candidate)}-{digest[:12]}{suffix}"
        # Copy from the verified descriptor: re-opening the path would follow
        # whatever a concurrent writer put there, such as a FIFO that blocks.
        imported = service.import_descriptor(
            descriptor,
            suffix=suffix,
            expected_sha256=digest,
            output_name=output_name,
            reuse_identical=True,
        )
    finally:
        os.close(descriptor)
    return {
        **imported,
        "source_filename": unicodedata.normalize("NFC", candidate.name),
    }
