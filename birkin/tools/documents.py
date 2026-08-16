"""Registered Office Work OS document tools."""
from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from ..office.active_content_schema import (
    ACTIVE_CONTENT_CONSENT_SCHEMA,
    PATCH_OPERATION_SCHEMA,
)
from ..office.adapters.catalog import supported_formats
from ..office.conversion_tool import budget_schema, execute_tool_conversion
from ..office.create_schema import create_content_schema
from ..office.errors import DocumentError, DocumentErrorCode
from ..office.service import DocumentService
from ._types import Tool, ToolContext, ToolInput, ToolResult

NAMES = (
    "list_document_adapters",
    "inspect_document",
    "extract_document",
    "create_document",
    "compare_documents",
    "fill_template",
    "apply_document_patch",
    "render_artifact",
    "validate_artifact",
    "convert_document",
)

_ARTIFACT = {
    "type": "object",
    "properties": {
        "artifact_id": {"type": "string"},
        "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "media_type": {"type": "string"},
        "uri": {"type": "string"},
        "sensitivity": {"type": "string"},
        "acl_fingerprint": {"type": "string"},
    },
    "required": ["content_hash", "uri"],
    "additionalProperties": False,
}
_OUTPUT_NAME = {
    "type": "string",
    "minLength": 1,
    "description": "Logical file name emitted under the managed drafts directory.",
}


def _object(properties: dict[str, object], required: list[str] | None = None) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _payload(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("tool input must be an object")
    payload: dict[str, object] = {}
    raw = cast("Mapping[object, object]", value)
    for key, item in raw.items():
        if not isinstance(key, str):
            raise TypeError("tool input keys must be strings")
        payload[key] = item
    return payload


def _handler(name: str) -> Callable[[ToolInput, ToolContext], ToolResult]:
    def run(data: ToolInput, ctx: ToolContext) -> ToolResult:
        _ = ctx
        home = Path(os.environ.get("BIRKIN_HOME", Path.home() / ".birkin"))
        service = DocumentService(home)
        try:
            if name == "list_document_adapters":
                result: object = {"adapters": service.adapter_inventory()}
            elif name == "render_artifact":
                payload = _payload(data)
                if "output_format" not in payload:
                    result = DocumentError(
                        DocumentErrorCode.CAPABILITY_UNAVAILABLE,
                        "render",
                        "visual rendering requires an approved pinned renderer",
                    ).envelope()
                else:
                    artifact = cast("Mapping[str, object]", payload["artifact"])
                    output_format = cast("str", payload["output_format"])
                    page = cast("int | None", payload.get("page"))
                    result = service.render_artifact(
                        artifact, output_format=output_format, page=page
                    )
            elif name == "convert_document":
                result = execute_tool_conversion(home, service, _payload(data))
            else:
                methods: dict[str, Callable[..., object]] = {
                    "inspect_document": service.inspect_document,
                    "extract_document": service.extract_document,
                    "create_document": service.create_document,
                    "compare_documents": service.compare_documents,
                    "fill_template": service.fill_template,
                    "apply_document_patch": service.apply_document_patch,
                    "validate_artifact": service.validate_artifact,
                }
                result = methods[name](**_payload(data))
            return ToolResult(
                json.dumps(result, ensure_ascii=False, default=str),
                is_error=isinstance(result, Mapping) and "error" in result,
            )
        except DocumentError as exc:
            return ToolResult(
                json.dumps(exc.envelope(), ensure_ascii=False), is_error=True
            )
        except (KeyError, TypeError, ValueError) as exc:
            error = DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "plan",
                f"invalid {name} input: {exc}",
            )
            return ToolResult(
                json.dumps(error.envelope(), ensure_ascii=False), is_error=True
            )

    return run


def tools() -> list[Tool]:
    schemas = {
        "list_document_adapters": _object({}),
        "inspect_document": _object({"source": _ARTIFACT}, ["source"]),
        "extract_document": _object(
            {
                "source": _ARTIFACT,
                "projection": {"type": "string", "enum": ["text"]},
                "max_spans": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10_000,
                },
                "max_nodes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10_000,
                },
                "max_text_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1_000_000,
                },
            },
            ["source"],
        ),
        "create_document": _object(
            {
                "format": {
                    "type": "string",
                    "enum": list(supported_formats("create")),
                },
                "content": create_content_schema(),
                "output_name": _OUTPUT_NAME,
                "template": _ARTIFACT,
            },
            ["format", "content", "output_name"],
        ),
        "compare_documents": _object(
            {"left": _ARTIFACT, "right": _ARTIFACT}, ["left", "right"]
        ),
        "fill_template": _object(
            {
                "template": _ARTIFACT,
                "bindings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "value": {},
                        },
                        "required": ["key", "value"],
                        "additionalProperties": False,
                    },
                },
                "output_name": _OUTPUT_NAME,
                "fields": {"type": "array", "items": {"type": "object"}},
                "strict": {"type": "boolean"},
                "raw_token_fallback": {"type": "boolean"},
            },
            ["template", "bindings", "output_name"],
        ),
        "apply_document_patch": _object(
            {
                "base": _ARTIFACT,
                "patch": {
                    "type": "object",
                    "properties": {
                        "operations": {
                            "type": "array",
                            "items": PATCH_OPERATION_SCHEMA,
                        },
                        "active_content_consent": ACTIVE_CONTENT_CONSENT_SCHEMA,
                    },
                    "required": ["operations"],
                    "additionalProperties": False,
                },
                "expected_source_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "output_name": _OUTPUT_NAME,
                "dry_run": {"type": "boolean"},
            },
            ["base", "patch", "expected_source_sha256", "output_name"],
        ),
        "render_artifact": _object(
            {
                "artifact": _ARTIFACT,
                "output_format": {
                    "type": "string",
                    "enum": ["structured_preview", "pdf", "png", "thumbnail"],
                },
                "page": {"type": "integer", "minimum": 1},
            },
            ["artifact"],
        ),
        "validate_artifact": _object({"artifact": _ARTIFACT}, ["artifact"]),
        "convert_document": _object(
            {
                "source": _ARTIFACT,
                "target_format": {"type": "string", "enum": ["txt"]},
                "output_name": _OUTPUT_NAME,
                "loss_budget": budget_schema(),
            },
            ["source", "target_format", "output_name", "loss_budget"],
        ),
    }
    return [
        Tool(
            name,
            f"Office Work OS: {name.replace('_', ' ')}.",
            schemas[name],
            _handler(name),
        )
        for name in NAMES
    ]
