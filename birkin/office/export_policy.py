"""Allowlisted, durable export and rollback for validated Office drafts."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias, final

from .artifact_snapshot import SnapshotPath
from .errors import DocumentError, DocumentErrorCode
from .path_security import directory_identity, ensure_directory_identity, sync_directory


JSONValue: TypeAlias = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]


@dataclass(frozen=True, slots=True)
class ExportRequest:
    """Caller-owned export destination and its separate approvals."""

    destination: Path
    actor: str
    proposal_digest: str
    operations: tuple[Mapping[str, JSONValue], ...]
    overwrite_approved: bool = False


@dataclass(frozen=True, slots=True)
class ExportReceipt:
    """Audit receipt plus private state required for exact rollback."""

    rollback_token: str
    destination: Path
    source_sha256: str
    output_sha256: str
    operations: tuple[dict[str, JSONValue], ...]
    actor: str
    proposal_digest: str
    destination_existed: bool
    destination_sha256: str | None
    backup: Path | None

    def public(self) -> dict[str, JSONValue]:
        return {
            "path": str(self.destination), "source_sha256": self.source_sha256,
            "output_sha256": self.output_sha256,
            "operations": [dict(operation) for operation in self.operations],
            "actor": self.actor, "proposal_digest": self.proposal_digest,
            "destination_existed": self.destination_existed,
            "destination_sha256": self.destination_sha256,
            "rollback_token": self.rollback_token,
        }


@dataclass(frozen=True, slots=True)
class RollbackReceipt:
    destination: Path
    restored: bool
    destination_sha256: str | None
    actor: str
    proposal_digest: str

    def public(self) -> dict[str, JSONValue]:
        return {
            "path": str(self.destination), "restored": self.restored,
            "destination_sha256": self.destination_sha256,
            "actor": self.actor, "proposal_digest": self.proposal_digest,
        }


@final
class ExportPolicy:
    """Copy immutable drafts into one caller-approved filesystem root."""

    def __init__(self, drafts: Path, export_root: Path, backup_root: Path) -> None:
        self._drafts = drafts
        self._draft_identity = directory_identity(drafts)
        configured_root = Path(export_root).absolute()
        if configured_root.is_symlink() or not configured_root.is_dir():
            raise self._denied("export root must be an existing real directory")
        self._root = configured_root.resolve(strict=True)
        self._root_identity = directory_identity(self._root)
        self._backup_root = backup_root

    def export(self, source: SnapshotPath, request: ExportRequest) -> ExportReceipt:
        """Durably replace only the resolved, allowlisted caller destination."""
        ensure_directory_identity(self._drafts, self._draft_identity)
        if not source.is_relative_to(self._drafts):
            raise self._denied("export source is not a managed validated draft")
        destination = self.resolve_destination(request.destination)
        parent_identity = directory_identity(destination.parent)
        if not request.actor or not request.proposal_digest or not request.operations:
            raise DocumentError(
                DocumentErrorCode.PRECONDITION_FAILED,
                "export",
                "actor, proposal digest, and operations are required",
            )
        existed = destination.exists() or destination.is_symlink()
        if existed and not request.overwrite_approved:
            raise DocumentError(
                DocumentErrorCode.OUTPUT_EXISTS,
                "export",
                "destination exists and overwrite approval is absent",
                details={"reason": "overwrite_approval_required"},
            )
        if existed and (destination.is_symlink() or not destination.is_file()):
            raise self._denied("export destination must be a regular file")

        source_sha256 = source.sha256()
        prior_sha256: str | None = None
        backup: Path | None = None
        temporary: Path | None = None
        reservation: int | None = None
        try:
            if existed:
                backup, prior_sha256 = self._snapshot_destination(destination)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".birkin-export-", suffix=destination.suffix, dir=destination.parent
            )
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as outgoing, os.fdopen(
                os.open(source, os.O_RDONLY), "rb"
            ) as incoming:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            output_sha256 = self._hash(temporary)
            if output_sha256 != source_sha256:
                raise DocumentError(
                    DocumentErrorCode.SOURCE_CHANGED,
                    "export",
                    "export copy does not match the validated draft",
                    artifact_sha256=output_sha256,
                )
            ensure_directory_identity(self._root, self._root_identity)
            ensure_directory_identity(destination.parent, parent_identity)
            if not existed:
                reservation = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(reservation)
                reservation = None
            elif self._hash(destination) != prior_sha256:
                raise DocumentError(
                    DocumentErrorCode.SOURCE_CHANGED,
                    "export",
                    "destination changed after its rollback snapshot",
                )
            os.replace(temporary, destination)
            temporary = None
            sync_directory(destination.parent, parent_identity)
            return ExportReceipt(
                rollback_token=uuid.uuid4().hex,
                destination=destination,
                source_sha256=source_sha256,
                output_sha256=output_sha256,
                operations=tuple(dict(operation) for operation in request.operations),
                actor=request.actor,
                proposal_digest=request.proposal_digest,
                destination_existed=existed,
                destination_sha256=prior_sha256,
                backup=backup,
            )
        except (DocumentError, OSError):
            if reservation is not None:
                os.close(reservation)
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if backup is not None:
                backup.unlink(missing_ok=True)
            if not existed and destination.exists():
                destination.unlink(missing_ok=True)
            raise

    def rollback(self, receipt: ExportReceipt) -> RollbackReceipt:
        """Restore the exact pre-export destination after output identity proof."""
        destination = self.resolve_destination(receipt.destination)
        parent_identity = directory_identity(destination.parent)
        if not destination.is_file() or self._hash(destination) != receipt.output_sha256:
            raise DocumentError(
                DocumentErrorCode.SOURCE_CHANGED,
                "rollback",
                "exported destination changed after publication",
            )
        if receipt.destination_existed:
            backup = receipt.backup
            if backup is None or not backup.is_file():
                raise DocumentError(
                    DocumentErrorCode.PRECONDITION_FAILED,
                    "rollback",
                    "destination backup is unavailable",
                )
            temporary = self._copy_to_temporary(backup, destination.parent, destination.suffix)
            try:
                if self._hash(temporary) != receipt.destination_sha256:
                    raise DocumentError(
                        DocumentErrorCode.SOURCE_CHANGED,
                        "rollback",
                        "destination backup hash mismatch",
                    )
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            backup.unlink()
        else:
            destination.unlink()
        sync_directory(destination.parent, parent_identity)
        return RollbackReceipt(
            destination=destination, restored=receipt.destination_existed,
            destination_sha256=receipt.destination_sha256, actor=receipt.actor,
            proposal_digest=receipt.proposal_digest,
        )

    def resolve_destination(self, requested: Path) -> Path:
        """Resolve a caller path without permitting symlinked root escapes."""
        raw = Path(requested)
        candidate = raw if raw.is_absolute() else self._root / raw
        absolute = candidate.absolute()
        parent = absolute.parent
        try:
            resolved_parent = parent.resolve(strict=True)
        except OSError as exc:
            raise self._denied("export destination parent is unavailable") from exc
        if resolved_parent != parent or not resolved_parent.is_relative_to(self._root):
            raise self._denied("export destination escapes the allowlisted root")
        ensure_directory_identity(self._root, self._root_identity)
        if absolute.name in {"", ".", ".."}:
            raise self._denied("export destination requires a filename")
        return absolute

    def _snapshot_destination(self, destination: Path) -> tuple[Path, str]:
        self._backup_root.mkdir(mode=0o700, exist_ok=True)
        if self._backup_root.is_symlink():
            raise self._denied("export backup directory must not be a symbolic link")
        os.chmod(self._backup_root, 0o700)
        backup = self._backup_root / f"{uuid.uuid4().hex}.bak"
        temporary = self._copy_to_temporary(
            destination, self._backup_root, destination.suffix
        )
        digest = self._hash(temporary)
        os.replace(temporary, backup)
        sync_directory(self._backup_root, directory_identity(self._backup_root))
        return backup, digest

    @staticmethod
    def _copy_to_temporary(source: Path, directory: Path, suffix: str) -> Path:
        descriptor, name = tempfile.mkstemp(
            prefix=".birkin-export-", suffix=suffix, dir=directory
        )
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as outgoing, source.open("rb") as incoming:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                outgoing.flush()
                os.fsync(outgoing.fileno())
        except OSError:
            temporary.unlink(missing_ok=True)
            raise
        return temporary

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _denied(message: str) -> DocumentError:
        return DocumentError(DocumentErrorCode.PERMISSION_DENIED, "export", message)
