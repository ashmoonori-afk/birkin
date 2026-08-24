"""Template planning and narrow copy-on-write patch operations."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import cast

from .active_content_consent import (
    inspect_active_content,
    require_preservation_consent,
    verify_preserved,
)
from .adapters.docx import DocxAdapter
from .adapters.hwpx import HwpxAdapter
from .adapters.hwpx_package import require_hwpx_content
from .adapters.pptx import PptxAdapter
from .adapters.xlsx import XlsxAdapter
from .docx_patch_locator import resolve_docx_paragraph
from .errors import DocumentError, DocumentErrorCode
from .service_patch_contract import validate_operations
from .service_workspace import DocumentWorkspace
from .template import (
    TemplateField,
    bind_patch_operations,
    binding_values,
    native_template_fields,
)


def _invalid(message: str) -> DocumentError:
    return DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", message)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{label} must be an object")
    entries: dict[str, object] = {}
    for key, item in cast("Mapping[object, object]", value).items():
        if not isinstance(key, str):
            raise _invalid(f"{label} keys must be strings")
        entries[key] = item
    return entries


def _operations(patch: Mapping[str, object]) -> list[dict[str, object]]:
    value = patch.get("operations", [])
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _invalid("patch operations must be a list")
    return [dict(_mapping(item, "patch operation")) for item in value]


def _string(operation: Mapping[str, object], key: str) -> str:
    value = operation.get(key)
    if not isinstance(value, str):
        raise _invalid(f"patch operation {key!r} must be a string")
    return value


def _template_summary(source: Path, format_name: str) -> Mapping[str, object]:
    adapters = {
        "docx": DocxAdapter,
        "hwpx": HwpxAdapter,
        "xlsx": XlsxAdapter,
        "pptx": PptxAdapter,
    }
    adapter = adapters.get(format_name)
    if adapter is None:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "plan",
            f"{format_name} template fill is unsupported",
        )
    return adapter().inspect(source)


def fill_template(
    workspace: DocumentWorkspace,
    template: Mapping[str, object],
    bindings: object,
    *,
    output_name: object,
    fields: object = None,
    strict: object = True,
    raw_token_fallback: object = False,
) -> dict[str, object]:
    if not isinstance(strict, bool) or not isinstance(raw_token_fallback, bool):
        raise _invalid("template options must be booleans")
    values = binding_values(bindings)
    with workspace.artifact_snapshot(template) as source:
        format_name = source.suffix.lower().lstrip(".")
        validate_operations(
            format_name, (), operation_name="fill", require_single=False
        )
        if format_name == "hwpx":
            require_hwpx_content(source)
        _ = workspace.output_path(output_name, source.suffix.lower())
        summary = _template_summary(source, format_name)
        if fields is None:
            field_list = native_template_fields(format_name, summary)
        elif isinstance(fields, Sequence) and not isinstance(fields, (str, bytes)):
            field_list: list[TemplateField] = [
                _mapping(field, "template field") for field in fields
            ]
        else:
            raise _invalid("template fields must be a list")
        operations = bind_patch_operations(
            format_name,
            field_list,
            values,
            strict=strict,
            raw_token_fallback=raw_token_fallback,
        )
        validate_operations(
            format_name, operations, operation_name="fill", require_single=False
        )
        digest = workspace.hash_file(source)
    return {
        "status": "planned",
        "format": format_name,
        "template_sha256": digest,
        "source_sha256": digest,
        "expected_source_sha256": digest,
        "output_name": output_name,
        "operations": operations,
        "patch": {"operations": operations},
        "draft_artifact": None,
        "dry_run": True,
    }


def _patch_writer(
    source: Path,
    fmt: str,
    operation: Mapping[str, object],
    expected_sha256: str,
) -> Callable[[Path], None]:
    def write(target: Path) -> None:
        target_fd = os.open(
            target,
            os.O_WRONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_BINARY", 0),
        )
        descriptor, name = tempfile.mkstemp(dir=target.parent, suffix=source.suffix)
        os.close(descriptor)
        staging = Path(name)
        staging.unlink()
        value = operation.get("value")
        try:
            if fmt == "docx" and "locator" in operation:
                if not isinstance(value, str):
                    raise _invalid("DOCX paragraph patch value must be a string")
                selector = operation.get("locator")
                if not isinstance(selector, Mapping):
                    raise _invalid("DOCX paragraph locator must be an object")
                adapter = DocxAdapter()
                _ = adapter.patch_text(
                    source,
                    staging,
                    resolve_docx_paragraph(source, selector),
                    value,
                    expected_source_sha256=expected_sha256,
                )
            elif fmt in {"docx", "hwpx"}:
                if not isinstance(value, str):
                    raise _invalid("field patch value must be a string")
                adapter = DocxAdapter() if fmt == "docx" else HwpxAdapter()
                _ = adapter.patch_field(source, staging, _string(operation, "field"), value, expected_source_sha256=expected_sha256)
            elif fmt == "xlsx":
                _ = XlsxAdapter().patch_cell(source, staging, _string(operation, "cell"), value, expected_source_sha256=expected_sha256)
            elif fmt == "pptx":
                index = operation.get("placeholder_idx")
                if not isinstance(index, int) or isinstance(index, bool):
                    raise _invalid("patch operation 'placeholder_idx' must be an integer")
                if not isinstance(value, str):
                    raise _invalid("placeholder patch value must be a string")
                _ = PptxAdapter().patch_placeholder(source, staging, index, value, expected_source_sha256=expected_sha256)
            else:
                raise DocumentError(DocumentErrorCode.UNSUPPORTED_EDIT, "apply", "format is read only")
            payload = staging.read_bytes()
            os.ftruncate(target_fd, 0)
            view = memoryview(payload)
            while view:
                written = os.write(target_fd, view)
                view = view[written:]
        finally:
            os.close(target_fd)
            staging.unlink(missing_ok=True)
    return write


def apply_document_patch(
    workspace: DocumentWorkspace,
    base: Mapping[str, object],
    patch: dict[str, object],
    *,
    expected_source_sha256: str,
    output_name: str,
    dry_run: bool = True,
) -> dict[str, object]:
    if expected_source_sha256 != base.get("content_hash"):
        raise DocumentError(DocumentErrorCode.SOURCE_CHANGED, "apply", "expected source hash mismatch")
    allowed_patch_keys = {"operations", "active_content_consent"}
    if set(patch) - allowed_patch_keys:
        raise _invalid(f"unsupported patch fields: {sorted(set(patch) - allowed_patch_keys)}")
    operations = _operations(patch)
    with workspace.artifact_snapshot(base) as source:
        fmt = source.suffix.lower().lstrip(".")
        if fmt == "hwpx":
            require_hwpx_content(source)
        validate_operations(
            fmt, operations, operation_name="patch", require_single=True
        )
        evidence = inspect_active_content(source)
        if evidence["source_sha256"] != expected_source_sha256:
            raise DocumentError(
                DocumentErrorCode.SOURCE_CHANGED, "preflight",
                "source changed during active-content preflight",
                artifact_sha256=evidence["source_sha256"],
            )
        output = workspace.output_path(output_name, source.suffix.lower())
        if dry_run:
            return {
                "status": "planned", "draft_artifact": None, "ir_artifact": None,
                "edit_log": operations, "semantic_diff": {}, "package_diff": {},
                "source_sha256": expected_source_sha256, "active_content_evidence": evidence,
            }
        require_preservation_consent(evidence, patch.get("active_content_consent"))
        operation = operations[0]
        output_evidence: dict[str, object] = {}

        def validate(candidate: Path) -> None:
            nonlocal output_evidence
            workspace.ensure_drafts_identity()
            try:
                output_evidence = dict(verify_preserved(evidence, candidate))
            except Exception as exc:
                if isinstance(exc, DocumentError) and exc.code is DocumentErrorCode.POLICY_DENIED:
                    raise
                raise DocumentError(
                    DocumentErrorCode.POLICY_DENIED, "validate",
                    "draft active-content preservation could not be proven",
                    details={"reason": type(exc).__name__},
                ) from exc

        _ = workspace.atomic_publish(
            output, _patch_writer(source, fmt, operation, expected_source_sha256), validate
        )
        if workspace.hash_file(source) != expected_source_sha256:
            output.unlink(missing_ok=True)
            raise DocumentError(DocumentErrorCode.SOURCE_CHANGED, "validate", "source changed while the draft was produced")
    return {
        "status": "draft", "draft_artifact": workspace.artifact(output, base),
        "ir_artifact": None, "edit_log": operations, "semantic_diff": {},
        "package_diff": {}, "source_sha256": expected_source_sha256,
        "active_content_evidence": {
            **evidence, "output_inventory_sha256": output_evidence["inventory_sha256"],
            "preservation_mode": "preserve_exact", "preserved": True,
        },
    }
