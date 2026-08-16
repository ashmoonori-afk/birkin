"""Scoped content-addressed storage for raw capture artifacts."""

from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from .redaction import redact_text


@dataclass(frozen=True, slots=True)
class ArtifactError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class ArtifactScope:
    session_id: str
    app_ref: str
    window_ref: str
    snapshot_generation: int


@dataclass(frozen=True, slots=True)
class CaptureArtifact:
    ref: str
    byte_size: int
    media_type: str
    width: int
    height: int
    scope: ArtifactScope
    annotations: tuple[str, ...]
    raw_bytes: None = None


class ArtifactStore:
    def __init__(
        self,
        root: Path,
        *,
        max_bytes: int = 5 * 1024 * 1024,
        max_dimension: int = 8192,
        max_annotations: int = 256,
        max_artifacts: int = 256,
    ) -> None:
        self.root = root
        self.max_bytes = max_bytes
        self.max_dimension = max_dimension
        self.max_annotations = max_annotations
        self.max_artifacts = max_artifacts

    def put_capture(
        self,
        data: bytes,
        *,
        media_type: str,
        width: int,
        height: int,
        scope: ArtifactScope,
        isolated: bool,
        annotations: list[str] | None = None,
    ) -> CaptureArtifact:
        if not isolated:
            raise ArtifactError(
                "capture_isolation_unavailable",
                "The backend cannot prove exact-window capture isolation.",
            )
        if (
            not data
            or len(data) > self.max_bytes
            or width < 1
            or height < 1
            or width > self.max_dimension
            or height > self.max_dimension
        ):
            raise ArtifactError(
                "resource_limit",
                "The capture exceeds configured evidence bounds.",
            )
        if media_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ArtifactError(
                "unsupported",
                "The capture media type is not supported.",
            )
        import hashlib

        digest = hashlib.sha256(data).hexdigest()
        path = self.root / "sha256" / digest[:2] / digest
        self._write_once(path, data)
        self._prune()
        bounded = tuple(
            redact_text(annotation, max_chars=256)
            for annotation in (annotations or [])[: self.max_annotations]
        )
        return CaptureArtifact(
            ref=f"sha256:{digest}",
            byte_size=len(data),
            media_type=media_type,
            width=width,
            height=height,
            scope=scope,
            annotations=bounded,
        )

    def path_for(self, artifact: CaptureArtifact) -> Path:
        digest = artifact.ref.removeprefix("sha256:")
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ArtifactError("invalid_request", "Invalid artifact digest.")
        return self.root / "sha256" / digest[:2] / digest

    def _write_once(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        (self.root / "sha256").chmod(0o700)
        path.parent.chmod(0o700)
        if path.exists():
            path.chmod(0o600)
            return
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)

    def _prune(self) -> None:
        artifacts = sorted(
            (path for path in (self.root / "sha256").glob("*/*") if path.is_file()),
            key=lambda path: path.stat().st_mtime_ns,
        )
        for expired in artifacts[: -self.max_artifacts]:
            expired.unlink(missing_ok=True)
