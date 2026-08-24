"""Registered Office Work OS document tools."""
from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import cast

from ..office.active_content_schema import PATCH_OPERATION_SCHEMA
from ._types import Tool, ToolContext, ToolInput, ToolResult

NAMES = (
    "list_document_adapters",
    "inspect_document",
    "extract_document",
    "compare_documents",
    "render_artifact",
    "validate_artifact",
    "office_job_request",
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


def _operations(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError("operations must be an array")
    return tuple(_payload(item) for item in value)


def _handler(name: str) -> Callable[[ToolInput, ToolContext], ToolResult]:
    def run(data: ToolInput, ctx: ToolContext) -> ToolResult:
        from .. import approvals
        from ..office.coordinator import OfficeCaller, OfficeCoordinator, OfficeMutationRequest
        from ..office.errors import DocumentError, DocumentErrorCode
        from ..office.service import DocumentService

        home = Path(os.environ.get("BIRKIN_HOME", Path.home() / ".birkin"))
        service = DocumentService(home)
        try:
            payload = _payload(data)
            if name == "list_document_adapters":
                result: object = {"adapters": service.adapter_inventory()}
            elif name == "render_artifact":
                if "output_format" not in payload:
                    result = DocumentError(
                        DocumentErrorCode.CAPABILITY_UNAVAILABLE,
                        "render",
                        "visual rendering requires an approved pinned renderer",
                    ).envelope()
                else:
                    result = service.render_artifact(
                        cast("Mapping[str, object]", payload["artifact"]),
                        output_format=cast("str", payload["output_format"]),
                        page=cast("int | None", payload.get("page")),
                    )
            elif name == "office_job_request":
                coordinator = OfficeCoordinator(
                    OfficeCaller(
                        home=home,
                        allowlist_root=ctx.cwd,
                        actor=ctx.record_source,
                    )
                )
                approval = coordinator.request(
                    OfficeMutationRequest(
                        request_text=cast("str", payload["request"]),
                        source=cast("Mapping[str, object]", payload["source"]),
                        outcome=cast("str", payload["outcome"]),
                        operations=_operations(payload["operations"]),
                        destination=Path(cast("str", payload["destination"])),
                        overwrite_approved=cast("bool", payload.get("overwrite_approved", False)),
                    )
                )
                queued = approvals.propose(
                    category="office_job",
                    title=f"Office mutation: {payload['outcome']}",
                    description="\n".join(
                        cast("str", item["summary"])
                        for item in cast("list[dict[str, object]]", approval["semantic_summaries"])
                    ),
                    payload=approval,
                    cfg={},
                    origin=ctx.record_source,
                )
                result = {**queued, "category": "office_job", "approval": approval}
            else:
                methods: dict[str, Callable[..., object]] = {
                    "inspect_document": service.inspect_document,
                    "extract_document": service.extract_document,
                    "compare_documents": service.compare_documents,
                    "validate_artifact": service.validate_artifact,
                }
                result = methods[name](**payload)
            return ToolResult(
                json.dumps(result, ensure_ascii=False, default=str),
                is_error=isinstance(result, Mapping) and "error" in result,
            )
        except DocumentError as exc:
            return ToolResult(json.dumps(exc.envelope(), ensure_ascii=False), is_error=True)
        except (KeyError, TypeError, ValueError) as exc:
            error = DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "plan",
                f"invalid {name} input: {exc}",
            )
            return ToolResult(json.dumps(error.envelope(), ensure_ascii=False), is_error=True)

    return run


def tools() -> list[Tool]:
    schemas = {
        "list_document_adapters": _object({}),
        "inspect_document": _object({"source": _ARTIFACT}, ["source"]),
        "extract_document": _object(
            {
                "source": _ARTIFACT,
                "projection": {"type": "string", "enum": ["text"]},
                "max_spans": {"type": "integer", "minimum": 1, "maximum": 10_000},
                "max_nodes": {"type": "integer", "minimum": 1, "maximum": 10_000},
                "max_text_bytes": {"type": "integer", "minimum": 1, "maximum": 1_000_000},
            },
            ["source"],
        ),
        "compare_documents": _object({"left": _ARTIFACT, "right": _ARTIFACT}, ["left", "right"]),
        "render_artifact": _object(
            {
                "artifact": _ARTIFACT,
                "output_format": {"type": "string", "enum": ["structured_preview", "pdf", "png", "thumbnail"]},
                "page": {"type": "integer", "minimum": 1},
            },
            ["artifact"],
        ),
        "validate_artifact": _object({"artifact": _ARTIFACT}, ["artifact"]),
        "office_job_request": _object(
            {
                "request": {"type": "string", "minLength": 1},
                "source": _ARTIFACT,
                "outcome": {"type": "string", "minLength": 1},
                "operations": {"type": "array", "minItems": 1, "items": PATCH_OPERATION_SCHEMA},
                "destination": {"type": "string", "minLength": 1},
                "overwrite_approved": {"type": "boolean"},
            },
            ["request", "source", "outcome", "operations", "destination"],
        ),
    }
    return [
        Tool(name, f"Office Work OS: {name.replace('_', ' ')}.", schemas[name], _handler(name))
        for name in NAMES
    ]
