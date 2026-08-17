"""Tool-boundary helpers for the document conversion contract."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from .service import DocumentService
from .service_create import convert_document
from .service_types import ConvertedDocument
from .service_workspace import DocumentWorkspace


def execute_tool_conversion(
    home: Path, service: DocumentService, payload: Mapping[str, object]
) -> ConvertedDocument:
    return convert_document(
        DocumentWorkspace(home),
        cast("Mapping[str, object]", payload["source"]),
        target_format=cast("str", payload["target_format"]),
        output_name=cast("str", payload["output_name"]),
        extract=service.extract_document,
        loss_budget=cast(
            "Mapping[str, object] | None", payload.get("loss_budget")
        ),
    )
