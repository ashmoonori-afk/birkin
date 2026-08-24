"""Resolve public structured-preview paragraph locators for DOCX patches."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .adapters.docx import DocxAdapter
from .adapters.docx_nodes import DocxLocator
from .errors import DocumentError, DocumentErrorCode


def resolve_docx_paragraph(
    source: Path, selector: Mapping[str, object]
) -> DocxLocator:
    """Bind a one-based public body-paragraph index to its stable locator."""
    index = selector.get("index")
    if not isinstance(index, int) or isinstance(index, bool):
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "plan",
            "DOCX paragraph locator index must be an integer",
        )
    paragraphs = DocxAdapter().inspect(source)["paragraphs"]
    target = next(
        (
            node
            for node in paragraphs
            if node["story"] == "body" and node["index"] == index - 1
        ),
        None,
    )
    if target is None:
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "plan",
            "DOCX paragraph locator did not match a body paragraph",
        )
    return target["locator"]
