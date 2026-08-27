"""Office job runner backed by the document service and managed workspace."""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import BinaryIO, cast, final

from .errors import DocumentError, DocumentErrorCode
from .execution_journal import ExecutionIntent, ExecutionJournal
from .export_policy import JSONValue, ExportReceipt, ExportRequest
from .export_receipt import restore_export_receipt
from .service import DocumentService
from .service_output import validate_output_name
from .service_workspace import DocumentWorkspace


def _precondition(message: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.PRECONDITION_FAILED,
        "office_job_runner",
        message,
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _precondition(f"{label} must be an object")
    raw = cast("Mapping[object, object]", value)
    if not all(isinstance(key, str) for key in raw):
        raise _precondition(f"{label} keys must be strings")
    return cast("Mapping[str, object]", raw)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise _precondition(f"{label} must be a non-empty string")
    return value


@final
class DocumentServiceRunner:
    """Run OfficeJob stages through a real DocumentService."""

    def __init__(
        self, service: DocumentService, *, export_root: Path | None = None
    ) -> None:
        self._service = service
        self._export_root = export_root
        self._export_receipts: dict[str, ExportReceipt] = {}

    def _source_sha256(self, source: Mapping[str, object]) -> str:
        inspection = self._service.inspect_document(source)
        identity = _mapping(inspection.get("source"), "inspection source")
        return _string(identity.get("sha256"), "inspection source sha256")

    def preview(
        self,
        *,
        source: Mapping[str, object],
        format_name: str,
        operations: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        source_sha256 = self._source_sha256(source)
        return self._service.apply_document_patch(
            base=source,
            patch={"operations": [dict(operation) for operation in operations]},
            expected_source_sha256=source_sha256,
            output_name=f"preview-{source_sha256[:16]}.{format_name}",
            dry_run=True,
        )

    def execute(
        self,
        *,
        source: Mapping[str, object],
        format_name: str,
        operations: Sequence[Mapping[str, object]],
        draft_name: str,
    ) -> dict[str, object]:
        source_sha256 = self._source_sha256(source)
        intent = ExecutionIntent.create(
            output_name=draft_name,
            source_sha256=source_sha256,
            format_name=format_name,
            operations=operations,
        )
        prepared = ExecutionJournal(self._service.home).prepare(intent)
        workspace = DocumentWorkspace(self._service.home)
        output = workspace.drafts / validate_output_name(
            draft_name, f".{format_name}"
        )
        if output.exists() or output.is_symlink():
            if not prepared:
                raise _precondition("managed draft predates its execution intent")
            recovered = workspace.artifact(output, source)
            sha256 = _string(recovered.get("content_hash"), "draft artifact sha256")
            raw: dict[str, object] = {
                "status": "draft",
                "draft_artifact": recovered,
            }
            return {"artifact": recovered, "sha256": sha256, "raw": raw}
        raw = self._service.apply_document_patch(
            base=source,
            patch={"operations": [dict(operation) for operation in operations]},
            expected_source_sha256=source_sha256,
            output_name=draft_name,
            dry_run=False,
        )
        artifact = _mapping(raw.get("draft_artifact"), "draft artifact")
        sha256 = _string(artifact.get("content_hash"), "draft artifact sha256")
        return {"artifact": artifact, "sha256": sha256, "raw": raw}

    def validate(self, *, artifact: Mapping[str, object]) -> dict[str, object]:
        return dict(self._service.validate_artifact(artifact))

    def export(
        self, *, artifact: Mapping[str, object], request: ExportRequest
    ) -> dict[str, JSONValue]:
        if self._export_root is None:
            raise _precondition("export root is not configured")
        workspace = DocumentWorkspace(self._service.home)
        policy = workspace.export_policy(self._export_root)
        snapshot = workspace.artifact_snapshot(artifact)
        with snapshot:
            receipt = policy.export(snapshot.path, request)
        self._export_receipts[receipt.rollback_token] = receipt
        return receipt.public()

    def rollback_export(
        self, receipt: Mapping[str, object]
    ) -> dict[str, JSONValue]:
        token = _string(receipt.get("rollback_token"), "rollback token")
        policy = DocumentWorkspace(self._service.home).export_policy(
            self._export_root
            or Path(_string(receipt.get("path"), "export path")).parent
        )
        supplied = restore_export_receipt(
            receipt,
            self._service.home / "artifacts" / "export-backups",
            policy.resolve_destination,
        )
        exported = self._export_receipts.get(token)
        if exported is not None and exported != supplied:
            raise _precondition("export receipt authority changed")
        exported = exported or supplied
        rolled_back = policy.rollback(exported)
        _ = self._export_receipts.pop(token, None)
        return rolled_back.public()

    def publish(
        self, *, artifact: Mapping[str, object], output_name: str
    ) -> dict[str, object]:
        workspace = DocumentWorkspace(self._service.home)
        with workspace.artifact_snapshot(artifact) as source:
            name = validate_output_name(output_name, source.suffix)
            output = workspace.drafts / name
            if output.exists() or output.is_symlink():
                published = workspace.artifact(output, artifact)
                sha256 = _string(
                    published.get("content_hash"), "publication artifact sha256"
                )
                if sha256 != _string(
                    artifact.get("content_hash"), "validated artifact sha256"
                ):
                    raise DocumentError(
                        DocumentErrorCode.SOURCE_CHANGED,
                        "office_job_runner",
                        "existing publication does not match the validated artifact",
                    )
                return {
                    "artifact": published,
                    "sha256": sha256,
                    "path": str(output),
                }
            output = workspace.output_path(name, source.suffix)

            def write(target: Path) -> None:
                with cast("BinaryIO", source.open("rb")) as incoming, target.open(
                    "wb"
                ) as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 1024 * 1024)

            sha256 = workspace.atomic_publish(output, write)
        published = workspace.artifact(output, artifact)
        return {
            "artifact": published,
            "sha256": sha256,
            "path": str(output),
        }
