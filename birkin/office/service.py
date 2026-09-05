"""Document service facade over immutable artifacts and format adapters."""

from __future__ import annotations

import hashlib
import os
import stat
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

from .adapters.catalog import AdapterInventory, adapter_inventory
from .adapters.docx import DocxAdapter
from .adapters.hwpx import HwpxAdapter
from .adapters.hwpx_package import require_hwpx_content
from .adapters.pdf import PdfAdapter
from .adapters.pptx import PptxAdapter
from .adapters.xlsx import XlsxAdapter
from .diff import compare_documents as build_document_diff
from .errors import DocumentError, DocumentErrorCode
from .extract import extract_items
from .extract_contract import (
    MAX_EXTRACTED_NODES,
    MAX_EXTRACTED_SPANS,
    MAX_TEXT_BYTES,
    build_extraction,
)
from .inspect_contract import build_inspection, verify_identity
from .meeting_actions import review_meeting_actions
from .render_contract import render_document
from .service_create import convert_document as convert_document_operation
from .service_create import create_document as create_document_operation
from .service_patch import apply_document_patch as apply_patch_operation
from .service_patch import fill_template as fill_template_operation
from .service_types import ConvertedDocument, CreatedDocument, ExtractionResult
from .service_workspace import DocumentWorkspace
from .validation import ValidationResult, validate_document
from .xlsx_analysis import analyze_xlsx


class _InspectAdapter(Protocol):
    def inspect(self, path: Path) -> Mapping[str, object]: ...


class DocumentService:
    """Single facade for registered Office Work OS operations."""

    home: Path
    _workspace: DocumentWorkspace

    def __init__(self, home: Path):
        self._workspace = DocumentWorkspace(home)
        self.home = self._workspace.home

    def adapter_inventory(self) -> list[AdapterInventory]:
        return adapter_inventory()

    @staticmethod
    def _snapshot_ref(ref: Mapping[str, object], path: Path) -> dict[str, object]:
        return {**ref, "uri": str(path)}

    @staticmethod
    def _require_content(path: Path, fmt: str) -> None:
        if fmt == "hwpx":
            require_hwpx_content(path)

    @staticmethod
    def _format(path: Path) -> str:
        return path.suffix.lower().lstrip(".")

    @staticmethod
    def _adapter(fmt: str) -> _InspectAdapter:
        if fmt == "docx":
            return DocxAdapter()
        if fmt == "xlsx":
            return XlsxAdapter()
        if fmt == "pptx":
            return PptxAdapter()
        if fmt == "hwpx":
            return HwpxAdapter()
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_FORMAT,
            "probe",
            f"unsupported format: {fmt}",
        )

    def create_document(
        self,
        *,
        format: str,
        content: Mapping[str, object],
        output_name: str,
        template: Mapping[str, object] | None = None,
    ) -> CreatedDocument:
        normalized = format.strip().lower().lstrip(".")
        font = content.get("font")
        if normalized == "pdf" and isinstance(font, Mapping):
            with self._workspace.artifact_snapshot(font) as snapshot:
                prepared = {**content, "font": self._snapshot_ref(font, snapshot)}
                return create_document_operation(
                    self._workspace,
                    format_name=format,
                    content=prepared,
                    output_name=output_name,
                    template=template,
                )
        if normalized != "hwpx" or template is None:
            return create_document_operation(self._workspace, format_name=format, content=content, output_name=output_name, template=template)
        with self._workspace.artifact_snapshot(template) as snapshot:
            require_hwpx_content(snapshot)
            return create_document_operation(
                self._workspace, format_name=format, content=content,
                output_name=output_name, template=self._snapshot_ref(template, snapshot),
            )

    def import_document(
        self,
        source: Path,
        *,
        expected_sha256: str,
        output_name: str,
    ) -> dict[str, object]:
        """Copy one authority-validated import into the document jail."""
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            source_fd = os.open(source, flags)
        except OSError as exc:
            raise DocumentError(
                DocumentErrorCode.PERMISSION_DENIED,
                "import",
                "registered import is unavailable",
            ) from exc
        try:
            metadata = os.fstat(source_fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise DocumentError(
                    DocumentErrorCode.PERMISSION_DENIED,
                    "import",
                    "registered import is not a regular file",
                )
            digest = hashlib.sha256()
            while chunk := os.read(source_fd, 1024 * 1024):
                digest.update(chunk)
            if digest.hexdigest() != expected_sha256:
                raise DocumentError(
                    DocumentErrorCode.SOURCE_CHANGED,
                    "import",
                    "registered import changed before document copy",
                )
            output = self._workspace.output_path(output_name, source.suffix.lower())

            def write(target: Path) -> None:
                _ = os.lseek(source_fd, 0, os.SEEK_SET)
                target_fd = os.open(
                    target,
                    os.O_WRONLY | getattr(os, "O_BINARY", 0),
                )
                copied = hashlib.sha256()
                try:
                    while chunk := os.read(source_fd, 1024 * 1024):
                        copied.update(chunk)
                        view = memoryview(chunk)
                        while view:
                            written = os.write(target_fd, view)
                            view = view[written:]
                    os.fsync(target_fd)
                finally:
                    os.close(target_fd)
                if copied.hexdigest() != expected_sha256:
                    raise DocumentError(
                        DocumentErrorCode.SOURCE_CHANGED,
                        "import",
                        "registered import changed during document copy",
                    )

            copied_sha256 = self._workspace.atomic_publish(output, write)
        finally:
            os.close(source_fd)
        artifact = self._workspace.artifact(output)
        return {
            "artifact": artifact,
            "receipt": {
                "operation": "document_import",
                "artifact_id": artifact["artifact_id"],
                "sha256": copied_sha256,
                "copied": True,
            },
        }

    def inspect_document(self, source: Mapping[str, object]) -> dict[str, object]:
        with self._workspace.artifact_snapshot(source) as path:
            fmt = self._format(path)
            summary: Mapping[str, object]
            if fmt == "hwpx":
                summary = HwpxAdapter().inspect(path)
                manifest = None if summary.get("encrypted") is True else verify_identity(path, fmt)
            elif fmt == "pdf":
                manifest = verify_identity(path, fmt)
                state = PdfAdapter().inspect(path)
                risks: list[dict[str, object]] = []
                active = state.get("active_content")
                if isinstance(active, list):
                    for raw_item in cast("list[object]", active):
                        if isinstance(raw_item, dict):
                            item = cast("dict[str, object]", raw_item)
                            risks.append({"code": "PDF_ACTIVE_CONTENT", **item})
                for present, code in (
                    (state.get("encrypted") is True, "PDF_ENCRYPTED"),
                    (state.get("signed") is True, "PDF_SIGNATURE"),
                    (state.get("form_type") == "xfa", "PDF_XFA_FORM"),
                ):
                    if present:
                        risks.append({"code": code})
                summary = {**state, "risks": risks}
            else:
                manifest = verify_identity(path, fmt)
                summary = self._adapter(fmt).inspect(path)
            inventory = next((item for item in self.adapter_inventory() if item["format"] == fmt), None)
            if inventory is None:
                raise DocumentError(DocumentErrorCode.UNSUPPORTED_FORMAT, "probe", f"unsupported format: {fmt}")
            digest = self._workspace.hash_file(path)
            return build_inspection(path, fmt, digest, summary, inventory, manifest)

    def extract_document(
        self,
        source: Mapping[str, object],
        *,
        projection: str = "text",
        max_spans: int = MAX_EXTRACTED_SPANS,
        max_nodes: int = MAX_EXTRACTED_NODES,
        max_text_bytes: int = MAX_TEXT_BYTES,
        max_chars: int | None = None,
    ) -> ExtractionResult:
        if max_chars is not None:
            if max_text_bytes != MAX_TEXT_BYTES:
                raise DocumentError(
                    DocumentErrorCode.INVALID_INPUT,
                    "extract",
                    "max_chars and max_text_bytes cannot both be set",
                )
            max_text_bytes = max_chars
        with self._workspace.artifact_snapshot(source) as path:
            fmt = self._format(path)
            self._require_content(path, fmt)
            _ = verify_identity(path, fmt)
            digest = self._workspace.hash_file(path)
            return build_extraction(
                extract_items(path, fmt), fmt, digest, projection=projection,
                max_spans=max_spans, max_nodes=max_nodes, max_text_bytes=max_text_bytes,
            )

    def analyze_workbook(
        self,
        source: Mapping[str, object],
        *,
        sheet: object,
        cell_range: object,
        group_by: object = None,
        value_column: object = None,
        compare_by: object = None,
        include_hidden_rows: object = False,
    ) -> dict[str, object]:
        with self._workspace.artifact_snapshot(source) as path:
            if self._format(path) != "xlsx":
                raise DocumentError(DocumentErrorCode.UNSUPPORTED_FORMAT, "analyze", "workbook analysis requires XLSX")
            _ = verify_identity(path, "xlsx")
            digest = self._workspace.hash_file(path)
            return analyze_xlsx(
                path, digest, sheet=sheet, cell_range=cell_range,
                group_by=group_by, value_column=value_column, compare_by=compare_by,
                include_hidden_rows=include_hidden_rows,
            )

    @staticmethod
    def review_meeting_actions(*, notes: object, candidates: object) -> dict[str, object]:
        return review_meeting_actions(notes, candidates)

    def validate_artifact(self, artifact: Mapping[str, object]) -> ValidationResult:
        with self._workspace.artifact_snapshot(artifact) as path:
            fmt = self._format(path)
            self._require_content(path, fmt)
            return validate_document(path, fmt)

    def convert_document(
        self,
        source: Mapping[str, object],
        *,
        target_format: str,
        output_name: str,
        loss_budget: Mapping[str, object] | None = None,
    ) -> ConvertedDocument:
        with self._workspace.artifact_snapshot(source) as path:
            self._require_content(path, self._format(path))
            return convert_document_operation(
                self._workspace, self._snapshot_ref(source, path),
                target_format=target_format, output_name=output_name,
                extract=self.extract_document, loss_budget=loss_budget,
            )

    def compare_documents(
        self,
        left: Mapping[str, object],
        right: Mapping[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        _ = kwargs
        with self._workspace.artifact_snapshot(left) as left_path, self._workspace.artifact_snapshot(right) as right_path:
            left_fmt, right_fmt = self._format(left_path), self._format(right_path)
            self._require_content(left_path, left_fmt)
            self._require_content(right_path, right_fmt)
            return build_document_diff(left_path, right_path, left_fmt, right_fmt)

    def render_artifact(
        self,
        artifact: Mapping[str, object],
        *,
        output_format: str = "png",
        page: int | None = None,
    ) -> dict[str, object]:
        with self._workspace.artifact_snapshot(artifact) as path:
            fmt = self._format(path)
            self._require_content(path, fmt)
            digest = self._workspace.hash_file(path)
            if fmt == "pdf" and output_format in {"png", "thumbnail"}:
                wanted = 1 if page is None else page
                output = self._workspace.output_path(
                    f"render-{digest[:16]}-p{wanted}-{uuid.uuid4().hex[:8]}.png",
                    ".png",
                )
                rendered: dict[str, object] = {}
                self._workspace.atomic_publish(
                    output,
                    lambda target: rendered.update(render_document(
                        path, fmt, digest, output_format=output_format, page=page,
                        output_path=target,
                    )),
                )
                output_artifact = self._workspace.artifact(output, artifact)
                rendered["output_artifact"] = output_artifact
                cast("dict[str, object]", rendered["receipt"])["output_artifact"] = output_artifact
                return rendered
            return render_document(path, fmt, digest, output_format=output_format, page=page)

    def fill_template(
        self,
        template: Mapping[str, object],
        bindings: list[dict[str, object]],
        *,
        output_name: str,
        fields: object = None,
        strict: object = True,
        raw_token_fallback: object = False,
    ) -> dict[str, object]:
        return fill_template_operation(
            self._workspace,
            template,
            bindings,
            output_name=output_name,
            fields=fields,
            strict=strict,
            raw_token_fallback=raw_token_fallback,
        )

    def apply_document_patch(
        self,
        base: Mapping[str, object],
        patch: dict[str, object],
        *,
        expected_source_sha256: str,
        output_name: str,
        dry_run: bool = True,
    ) -> dict[str, object]:
        return apply_patch_operation(
            self._workspace,
            base,
            patch,
            expected_source_sha256=expected_source_sha256,
            output_name=output_name,
            dry_run=dry_run,
        )
