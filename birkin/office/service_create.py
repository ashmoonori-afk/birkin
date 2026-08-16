"""Document service create and text-conversion operations."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from .adapters.catalog import supported_formats
from .adapters.hwpx import HwpxAdapter
from .conversion_engine import convert_document
from .create import create_document_file
from .create_template import HwpxTemplatePlan, plan_hwpx_template
from .errors import DocumentError, DocumentErrorCode
from .service_types import (
    CreatedDocument,
    CreationEvidence,
    CreationReceipt,
)
from .service_workspace import DocumentWorkspace

_CREATE_FORMATS = supported_formats("create")


def _create_hwpx(
    workspace: DocumentWorkspace,
    content: Mapping[str, object],
    template: Mapping[str, object] | None,
    output: Path,
) -> tuple[HwpxTemplatePlan, Path]:
    if template is None:
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", "HWPX creation requires a trusted template")
    source = workspace.resolve_artifact(template).resolve()
    if not source.is_relative_to(workspace.home):
        raise DocumentError(DocumentErrorCode.PERMISSION_DENIED, "import", "template escapes the configured home")
    if source.suffix.lower() != ".hwpx":
        raise DocumentError(DocumentErrorCode.UNSUPPORTED_FORMAT, "probe", "HWPX creation requires an HWPX template")
    if source == output.resolve():
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "emit", "template and destination must differ")
    plan = plan_hwpx_template(source, content)
    temporary_paths: list[Path] = []
    current = source
    expected = plan.source_sha256
    try:
        for binding in plan.bindings:
            descriptor, name = tempfile.mkstemp(dir=workspace.drafts, suffix=".hwpx")
            os.close(descriptor)
            temporary = Path(name)
            temporary.unlink()
            temporary_paths.append(temporary)
            _ = HwpxAdapter().patch_field(
                current,
                temporary,
                binding.key,
                binding.value,
                expected_text=binding.expected_text,
                expected_source_sha256=expected,
            )
            current = temporary
            expected = workspace.hash_file(current)
        if workspace.hash_file(source) != plan.source_sha256:
            raise DocumentError(
                DocumentErrorCode.SOURCE_CHANGED,
                "emit",
                "template changed during derivation",
                artifact_sha256=workspace.hash_file(source),
            )
        try:
            os.link(current, output)
        except FileExistsError as exc:
            raise DocumentError(DocumentErrorCode.OUTPUT_EXISTS, "emit", "output exists") from exc
    finally:
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)
    return plan, source


def _limits(format_name: str) -> tuple[list[str], list[str]]:
    capability = {
        "docx": ["paragraphs only", "maximum 10000 paragraphs"],
        "xlsx": ["scalar cell values only", "maximum 256 sheets and 100000 rows"],
        "pptx": ["title and body slides only", "maximum 10000 slides"],
        "pdf": ["text paragraphs only", "no forms, links, signatures, or encryption"],
        "hwpx": ["trusted HWPX template field bindings only", "templates are never executed"],
    }
    fidelity = {
        "docx": ["blank default Word styles; no layout or rendering claim"],
        "xlsx": ["blank default workbook styles; formulas are not calculated"],
        "pptx": ["default title-and-content layout; no rendering claim"],
        "pdf": ["text-first A4 output; line wrapping is approximate"],
        "hwpx": ["only matched field XML changes; all other package parts are preserved"],
    }
    return capability[format_name], fidelity[format_name]


def _result(
    workspace: DocumentWorkspace,
    output: Path,
    format_name: str,
    output_name: str,
    template: Mapping[str, object] | None,
    source_sha256: str | None,
    warnings: list[str],
) -> CreatedDocument:
    mode = "template_derivation" if source_sha256 is not None else "blank_authoring"
    artifact = workspace.artifact(output, template)
    output_sha256 = artifact["content_hash"]
    evidence: list[CreationEvidence] = [
        {"check": "plan_schema", "passed": True, "detail": "strict format plan validated before writing"},
        {"check": "destination", "passed": True, "detail": "new managed draft path emitted atomically"},
    ]
    if source_sha256 is not None:
        evidence.extend(
            [
                {"check": "template_identity", "passed": True, "detail": "template hash matched before and after derivation"},
                {"check": "template_bindings", "passed": True, "detail": "every binding matched exactly one field"},
                {"check": "template_execution", "passed": True, "detail": "template content was never executed"},
            ]
        )
    capability, fidelity = _limits(format_name)
    receipt: CreationReceipt = {
        "operation": "document_create",
        "version": 1,
        "format": format_name,
        "creation_mode": mode,
        "output_name": output_name,
        "source_sha256": source_sha256,
        "output_sha256": output_sha256,
    }
    return {
        "status": "draft",
        "draft_artifact": artifact,
        "format": format_name,
        "creation_mode": mode,
        "source_sha256": source_sha256,
        "template_sha256": source_sha256,
        "output_sha256": output_sha256,
        "capability_limits": capability,
        "fidelity_limits": fidelity,
        "validation_evidence": evidence,
        "warnings": warnings,
        "receipt": receipt,
    }


def create_document(
    workspace: DocumentWorkspace,
    *,
    format_name: str,
    content: Mapping[str, object],
    output_name: str,
    template: Mapping[str, object] | None = None,
) -> CreatedDocument:
    fmt = format_name.strip().lower().lstrip(".")
    if fmt not in _CREATE_FORMATS:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_FORMAT,
            "probe",
            f"unsupported creation format: {format_name}",
            details={"supported": list(_CREATE_FORMATS)},
        )
    output = workspace.output_path(output_name, f".{fmt}")
    workspace.enforce_content_limit(content)
    source_sha256: str | None = None
    warnings: list[str] = []
    if fmt == "hwpx":
        plan, _ = _create_hwpx(workspace, content, template, output)
        source_sha256 = plan.source_sha256
        warnings.extend(plan.warnings)
    else:
        if template is not None:
            raise DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", "template derivation is supported only for HWPX")
        create_document_file(fmt, content, output)
    return _result(workspace, output, fmt, output_name, template, source_sha256, warnings)


__all__ = ["convert_document", "create_document"]
