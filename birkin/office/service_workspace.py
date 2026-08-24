"""Managed document workspace paths, artifacts, and content limits."""

from __future__ import annotations

import hashlib
import mimetypes
import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import cast

from .artifact_identity import verify_descriptor_identity
from .artifact_publication import publish_once
from .artifact_serialization import canonical_json, sanitize_data
from .artifact_snapshot import ArtifactSnapshot as _ArtifactSnapshot
from .artifact_snapshot import SnapshotPath, protect_snapshot, sync_read_descriptor
from .artifact_snapshot import snapshot_from_descriptor as _snapshot_from_descriptor
from .errors import DocumentError, DocumentErrorCode
from .export_policy import ExportPolicy
from .path_security import (
    canonical_name,
    close_guard,
    directory_identity,
    enforce_content_limit,
    ensure_directory_identity,
    hash_descriptor,
    hash_path,
    open_directory_guard,
    open_regular,
    sync_directory,
)
from .service_output import validate_output_name
from .service_types import ArtifactRef

MAX_CONTENT_CHARS = 1_000_000
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024


def _prepare_private_directory(path: Path, *, parents: bool = False) -> None:
    """Create a private directory without following a pre-existing symlink."""
    path.mkdir(parents=parents, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise DocumentError(
            DocumentErrorCode.PERMISSION_DENIED,
            "emit",
            "managed workspace directory must not be a symbolic link",
        )
    if os.name == "posix":
        identity = directory_identity(path)
        descriptor = open_directory_guard(path, identity)
        try:
            os.fchmod(descriptor, 0o700)
        finally:
            close_guard(descriptor)
    else:
        os.chmod(path, 0o700)


class DocumentWorkspace:
    """Exact filesystem jail and deterministic artifact boundary."""

    home: Path
    configured_home: Path
    drafts: Path
    _draft_identity: tuple[int, int]
    def __init__(self, home: Path):
        configured = Path(home).absolute()
        _prepare_private_directory(configured, parents=True)
        self.configured_home = configured
        self.home = configured.resolve(strict=True)
        artifacts = self.home / "artifacts"
        _prepare_private_directory(artifacts)
        drafts = artifacts / "drafts"
        _prepare_private_directory(drafts)
        if drafts.is_symlink():
            raise DocumentError(
                DocumentErrorCode.PERMISSION_DENIED,
                "emit",
                "managed draft directory must not be a symbolic link",
            )
        self.drafts = drafts.resolve(strict=True)
        if self.drafts.parent.parent != self.home:
            raise DocumentError(
                DocumentErrorCode.PERMISSION_DENIED,
                "emit",
                "managed draft directory escapes the document home",
            )
        self._draft_identity = directory_identity(self.drafts)
        self._snapshots: dict[str, _ArtifactSnapshot] = {}

    @staticmethod
    def hash_file(path: Path | SnapshotPath) -> str:
        if isinstance(path, SnapshotPath):
            return path.sha256()
        return hash_path(path)

    def _register_snapshot(self, key: str, snapshot: _ArtifactSnapshot) -> None:
        if key in self._snapshots:
            raise DocumentError(
                DocumentErrorCode.INTERNAL_ERROR,
                "import",
                "artifact snapshot descriptor collision",
            )
        self._snapshots[key] = snapshot

    def _unregister_snapshot(self, key: str, snapshot: _ArtifactSnapshot) -> None:
        if self._snapshots.get(key) is snapshot:
            del self._snapshots[key]

    def _active_snapshot(self, ref: Mapping[str, object]) -> _ArtifactSnapshot | None:
        uri = ref.get("uri")
        return self._snapshots.get(uri) if isinstance(uri, str) else None

    def _open_artifact(self, ref: Mapping[str, object]) -> tuple[Path, int, str]:
        uri, expected = ref.get("uri"), ref.get("content_hash")
        if not isinstance(uri, str) or not uri or not isinstance(expected, str):
            raise DocumentError(DocumentErrorCode.INVALID_INPUT, "import", "artifact requires string uri and content_hash fields")
        active = self._active_snapshot(ref)
        if active is not None:
            return active.duplicate(expected)
        path = Path(uri)
        descriptor = open_regular(path, self.home, self.configured_home)
        if os.fstat(descriptor).st_size > MAX_ARTIFACT_BYTES:
            os.close(descriptor)
            raise DocumentError(
                DocumentErrorCode.LIMIT_EXCEEDED,
                "import",
                "artifact byte limit exceeded",
                details={
                    "reason": "artifact_bytes",
                    "maximum": MAX_ARTIFACT_BYTES,
                },
            )
        digest = hash_descriptor(descriptor)
        try:
            _ = verify_descriptor_identity(descriptor, path)
            current_descriptor = open_regular(path, self.home, self.configured_home)
            try:
                current, opened = os.fstat(current_descriptor), os.fstat(descriptor)
            finally:
                os.close(current_descriptor)
            current_id = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
            opened_id = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            if current_id != opened_id:
                raise DocumentError(DocumentErrorCode.SOURCE_CHANGED, "import", "artifact changed while its identity was verified", artifact_sha256=digest)
            if digest != expected:
                raise DocumentError(DocumentErrorCode.SOURCE_CHANGED, "import", "artifact hash mismatch", artifact_sha256=digest)
            return path, descriptor, digest
        except DocumentError as exc:
            os.close(descriptor)
            if exc.code in {DocumentErrorCode.INVALID_INPUT, DocumentErrorCode.PERMISSION_DENIED}:
                raise DocumentError(DocumentErrorCode.SOURCE_CHANGED, "import", "artifact changed while its identity was verified", artifact_sha256=digest) from exc
            raise

    def resolve_artifact(self, ref: Mapping[str, object]) -> Path:
        active = self._active_snapshot(ref)
        if active is not None:
            active.verify(ref.get("content_hash"))
            return cast(Path, cast(object, active.path))
        path, descriptor, _ = self._open_artifact(ref)
        os.close(descriptor)
        if path.suffix.lower() == ".hwpx":
            from .adapters.hwpx_package import require_hwpx_content

            require_hwpx_content(path)
        return path

    def artifact_snapshot(self, ref: Mapping[str, object]) -> _ArtifactSnapshot:
        """Return a private snapshot consumed through one verified identity."""
        source, source_fd, digest = self._open_artifact(ref)
        return _snapshot_from_descriptor(
            source,
            source_fd,
            digest,
            self.home,
            self.configured_home,
            self._register_snapshot,
            self._unregister_snapshot,
            protect_snapshot,
        )

    def _check_output_name(self, output_name: object, suffix: str) -> str:
        return validate_output_name(output_name, suffix)

    def ensure_drafts_identity(self) -> None:
        ensure_directory_identity(self.drafts, self._draft_identity)

    def export_policy(self, root: Path) -> ExportPolicy:
        self.ensure_drafts_identity()
        return ExportPolicy(self.drafts, root, self.drafts.parent / "export-backups")

    def output_path(self, output_name: object, suffix: str) -> Path:
        name = self._check_output_name(output_name, suffix)
        ensure_directory_identity(self.drafts, self._draft_identity)
        wanted = canonical_name(name)
        try:
            collision = next((item for item in self.drafts.iterdir() if canonical_name(item.name) == wanted), None)
        except OSError as exc:
            raise DocumentError(DocumentErrorCode.PERMISSION_DENIED, "emit", "cannot inspect managed draft directory") from exc
        if collision is not None:
            raise DocumentError(DocumentErrorCode.OUTPUT_EXISTS, "emit", "output exists or canonically collides")
        return self.drafts / name

    def atomic_publish(
        self,
        output: Path,
        writer: Callable[[Path], None],
        validator: Callable[[Path], None] | None = None,
    ) -> str:
        """Write, validate, durably publish once, and remove all traces on failure."""
        output = Path(output)
        if output.parent != self.drafts:
            raise DocumentError(DocumentErrorCode.PERMISSION_DENIED, "emit", "destination escapes managed drafts")
        _ = self._check_output_name(output.name, output.suffix.lower())
        return publish_once(
            self.drafts,
            self._draft_identity,
            output,
            writer,
            validator,
            verify_descriptor_identity,
        )

    def artifact(self, path: Path, source: Mapping[str, object] | None = None) -> ArtifactRef:
        descriptor = open_regular(Path(path), self.home)
        managed = Path(path).parent == self.drafts
        try:
            digest = hash_descriptor(descriptor)
            _ = verify_descriptor_identity(descriptor, Path(path))
            sync_read_descriptor(descriptor)
            if managed:
                sync_directory(self.drafts, self._draft_identity)
        except DocumentError:
            raise
        except OSError as exc:
            raise DocumentError(DocumentErrorCode.INTERNAL_ERROR, "emit", "artifact durability check failed") from exc
        finally:
            os.close(descriptor)
        return {
            "artifact_id": digest,
            "content_hash": digest,
            "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "uri": str(path),
            "sensitivity": str((source or {}).get("sensitivity", "unknown")),
            "acl_fingerprint": str((source or {}).get("acl_fingerprint", "")),
        }

    @staticmethod
    def receipt_digest(receipt: Mapping[str, object], *, secrets: Iterable[str] = ()) -> str:
        canonical = canonical_json(receipt, secrets=secrets).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @classmethod
    def artifact_receipt(
        cls,
        receipt: Mapping[str, object],
        *,
        generated_at: str,
        secrets: Iterable[str] = (),
    ) -> dict[str, object]:
        configured = tuple(secrets)
        core = sanitize_data(receipt, secrets=configured)
        metadata = sanitize_data({"generated_at": generated_at}, secrets=configured)
        return {
            "receipt": core,
            "receipt_digest": cls.receipt_digest(receipt, secrets=configured),
            "metadata": metadata,
        }

    @staticmethod
    def canonical_evidence(evidence: object, *, secrets: Iterable[str] = ()) -> str:
        return canonical_json(evidence, secrets=secrets)

    @staticmethod
    def enforce_content_limit(value: object) -> None:
        enforce_content_limit(value, MAX_CONTENT_CHARS)
