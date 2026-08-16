"""Deterministic structured text extraction entry point for Office formats."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from .adapters.catalog import supported_formats
from .adapters.pdf import PdfAdapter
from .errors import DocumentError, DocumentErrorCode
from .extract_package import extract_package_items
from .service_types import ExtractedItem

__all__ = ["SUPPORTED_FORMATS", "extract_items", "extract_text"]

SUPPORTED_FORMATS: Final = frozenset(supported_formats("extract"))


def _extract_pdf(path: Path) -> list[ExtractedItem]:
    spans = PdfAdapter().extract(path)
    line_numbers: dict[int, int] = {}
    items: list[ExtractedItem] = []
    for span in spans:
        text = span.get("text")
        page = span.get("page_no")
        if not isinstance(text, str) or not isinstance(page, int):
            raise DocumentError(
                DocumentErrorCode.INTERNAL_ERROR,
                "extract",
                "PDF adapter returned an invalid text span",
            )
        line_numbers[page] = line_numbers.get(page, 0) + 1
        method = span.get("method")
        items.append(
            {
                "text": text,
                "kind": "page_text",
                "locator": {"page": page, "line": line_numbers[page]},
                "method": method if isinstance(method, str) else "pypdf_native_text",
            }
        )
    return items


def extract_items(path: Path, format_name: str) -> list[ExtractedItem]:
    """Extract typed items in declared document reading order."""
    fmt = format_name.strip().lower().lstrip(".")
    if fmt not in SUPPORTED_FORMATS:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_FORMAT,
            "probe",
            f"unsupported format: {format_name}",
        )
    if fmt == "pdf":
        return _extract_pdf(path)
    return extract_package_items(path, fmt)


def extract_text(path: Path, format_name: str) -> list[str]:
    """Compatibility text projection over structured extraction."""
    return [item["text"] for item in extract_items(path, format_name)]
