"""Allowlisted, durable export and rollback for validated Office drafts."""

from __future__ import annotations

from pathlib import Path
from typing import final

from .artifact_snapshot import SnapshotPath
from .errors import DocumentError, DocumentErrorCode
from .export_transaction import ExportTransactionRunner
from .export_types import (
    JSONValue,
    ExportReceipt,
    ExportRequest,
    RollbackReceipt,
)
from .path_security import directory_identity, ensure_directory_identity, sync_directory


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
        if not request.actor or not request.proposal_digest or not request.operations:
            raise DocumentError(
                DocumentErrorCode.PRECONDITION_FAILED,
                "export",
                "actor, proposal digest, and operations are required",
            )
        ensure_directory_identity(self._root, self._root_identity)
        return ExportTransactionRunner(self._backup_root, sync_directory).export(
            source, destination, request
        )

    def rollback(self, receipt: ExportReceipt) -> RollbackReceipt:
        """Restore the exact pre-export destination after output identity proof."""
        destination = self.resolve_destination(receipt.destination)
        ensure_directory_identity(self._root, self._root_identity)
        return ExportTransactionRunner(self._backup_root, sync_directory).rollback(
            receipt, destination
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

    @staticmethod
    def _denied(message: str) -> DocumentError:
        return DocumentError(DocumentErrorCode.PERMISSION_DENIED, "export", message)


__all__ = [
    "JSONValue",
    "ExportPolicy",
    "ExportReceipt",
    "ExportRequest",
    "RollbackReceipt",
]
