from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Callable
from ..office.errors import DocumentError
from ..office.service import DocumentService
from ._types import Tool, ToolContext, ToolResult

NAMES = (
    "inspect_document", "extract_document", "compare_documents",
    "fill_template", "apply_document_patch", "render_artifact",
    "validate_artifact",
)


def _handler(name: str) -> Callable:
    def run(data: dict, ctx: ToolContext) -> ToolResult:
        home = Path(os.environ.get("BIRKIN_HOME", Path.home() / ".birkin"))
        service = DocumentService(home)
        try:
            if name == "render_artifact":
                result = service.unavailable("render")
            elif name == "validate_artifact":
                result = service.unavailable("validate")
            else:
                result = getattr(service, name)(**data)
            return ToolResult(
                json.dumps(result, ensure_ascii=False, default=str),
                is_error="error" in result,
            )
        except DocumentError as exc:
            return ToolResult(
                json.dumps(exc.envelope(), ensure_ascii=False), is_error=True
            )
    return run


def tools() -> list[Tool]:
    required = {
        "inspect_document": ["source"],
        "extract_document": ["source"],
        "compare_documents": ["left", "right"],
        "fill_template": ["template", "bindings", "output_name"],
        "apply_document_patch": [
            "base", "patch", "expected_source_sha256", "output_name"
        ],
        "render_artifact": ["artifact"],
        "validate_artifact": ["artifact"],
    }
    return [
        Tool(
            name,
            f"Office Work OS: {name.replace('_', ' ')}.",
            {
                "type": "object",
                "properties": {},
                "required": required[name],
                "additionalProperties": True,
            },
            _handler(name),
        )
        for name in NAMES
    ]
