"""Atomic creation entry point for validated text-first document plans."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from .adapters.catalog import supported_formats
from .create_backends import write_docx, write_hwpx, write_pptx, write_xlsx
from .create_content import ParagraphPlan, PresentationPlan, WorkbookPlan, validate_plan
from .create_pdf import write_pdf
from .errors import DocumentError, DocumentErrorCode

SUPPORTED_FORMATS: Final[tuple[str, ...]] = tuple(
    supported_formats("create")
)


def _write(format_name: str, plan: ParagraphPlan | WorkbookPlan | PresentationPlan, target: Path) -> None:
    if format_name == "docx" and isinstance(plan, ParagraphPlan):
        write_docx(plan, target)
    elif format_name == "hwpx" and isinstance(plan, ParagraphPlan):
        write_hwpx(plan, target)
    elif format_name == "pdf" and isinstance(plan, ParagraphPlan):
        write_pdf(plan, target)
    elif format_name == "xlsx" and isinstance(plan, WorkbookPlan):
        write_xlsx(plan, target)
    elif format_name == "pptx" and isinstance(plan, PresentationPlan):
        write_pptx(plan, target)
    else:
        raise DocumentError(DocumentErrorCode.INTERNAL_ERROR, "emit", "validated creation plan did not match its format")


def create_document_file(format_name: str, content: Mapping[str, object], output: Path) -> None:
    """Validate fully, then create without replacing an existing destination."""
    normalized = format_name.strip().lower()
    if normalized not in SUPPORTED_FORMATS:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_FORMAT,
            "probe",
            f"unsupported creation format: {format_name}",
            details={"supported": list(SUPPORTED_FORMATS)},
        )
    plan = validate_plan(normalized, content)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise DocumentError(DocumentErrorCode.OUTPUT_EXISTS, "emit", "output exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=output.parent, suffix=f".{normalized}.tmp")
    os.close(descriptor)
    temporary = Path(name)
    try:
        _write(normalized, plan, temporary)
        try:
            os.link(temporary, output)
        except FileExistsError as exc:
            raise DocumentError(DocumentErrorCode.OUTPUT_EXISTS, "emit", "output exists") from exc
    finally:
        temporary.unlink(missing_ok=True)


__all__ = ["SUPPORTED_FORMATS", "create_document_file"]
