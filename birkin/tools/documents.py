"""Registered Office Work OS document tools."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import cast

from ..office.active_content_schema import PATCH_OPERATION_SCHEMA
from ._types import Tool, ToolContext, ToolInput, ToolResult

NAMES = (
    "list_document_adapters",
    "inspect_document",
    "extract_document",
    "analyze_workbook",
    "review_meeting_actions",
    "compare_documents",
    "render_artifact",
    "validate_artifact",
    "office_job_request",
    "office_rollback_request",
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


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{name} must be an array")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise TypeError(f"{name} items must be strings")
        items.append(item)
    return tuple(items)


def _handler(name: str) -> Callable[[ToolInput, ToolContext], ToolResult]:
    def run(data: ToolInput, ctx: ToolContext) -> ToolResult:
        from .. import approvals
        from ..office.coordinator import OfficeCaller, OfficeCoordinator, OfficeMutationRequest
        from ..office.coordinator_data import canonical_office_home
        from ..office.create_approval import (
            OfficeCreationCaller,
            OfficeCreationCoordinator,
            OfficeCreationRequest,
        )
        from ..office.errors import DocumentError, DocumentErrorCode
        from ..office.progress import office_progress_sink
        from ..office.presentation import format_preview_replacements
        from ..office.preview_semantics import PreviewSummary
        from ..office.service import DocumentService

        home = canonical_office_home()
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
                if "source" in payload:
                    coordinator = OfficeCoordinator(
                        OfficeCaller(
                            allowlist_root=ctx.cwd,
                            actor=ctx.record_source,
                        ),
                        on_transition=office_progress_sink(ctx.emit),
                    )
                    approval = coordinator.request(
                        OfficeMutationRequest(
                            request_text=cast("str", payload["request"]),
                            source=cast("Mapping[str, object]", payload["source"]),
                            outcome=cast("str", payload["outcome"]),
                            operations=_operations(payload["operations"]),
                            destination=Path(cast("str", payload["destination"])),
                            overwrite_approved=cast(
                                "bool",
                                payload.get("overwrite_approved", False),
                            ),
                        )
                    )
                    semantic_summaries = cast(
                        "list[PreviewSummary]",
                        approval["semantic_summaries"],
                    )
                    title = f"Office 변경: {payload['outcome']}"
                    description = format_preview_replacements(semantic_summaries)
                    approval_category = "office_job"
                else:
                    raw_content = _payload(payload["content"])
                    paragraphs = (
                        _strings(raw_content["paragraphs"], "content paragraphs")
                        if set(raw_content) == {"paragraphs"}
                        else ()
                    )
                    coordinator = OfficeCreationCoordinator(
                        OfficeCreationCaller(
                            allowlist_root=ctx.cwd,
                            actor=ctx.record_source,
                        )
                    )
                    approval = coordinator.request(OfficeCreationRequest(
                        request_text=cast("str", payload["request"]),
                        paragraphs=paragraphs,
                        outcome=cast("str", payload["outcome"]),
                        destination=Path(cast("str", payload["destination"])),
                        overwrite_approved=cast(
                            "bool",
                            payload.get("overwrite_approved", False),
                        ),
                        content=raw_content if not paragraphs else None,
                        format_name=cast("str", payload["format"]),
                    ))
                    format_name = cast("str", payload["format"])
                    title = f"Office {format_name.upper()} 생성: {payload['outcome']}"
                    description = (
                        f"{format_name.upper()} 문서를 {'구조화된 내용으로' if not paragraphs else f'{len(paragraphs)}개 단락으로'} 생성합니다: "
                        f"{approval['destination']}."
                    )
                    approval_category = "office_create"
                queued = approvals.propose(
                    category=approval_category,
                    title=title,
                    description=description,
                    payload=approval,
                    cfg={},
                    origin=ctx.record_source,
                )
                result = {
                    **queued,
                    "category": approval_category,
                    "approval": approval,
                }
            elif name == "office_rollback_request":
                from ..office.rollback_approval import request_rollback

                result = request_rollback(
                    cast("str", payload["job_id"]),
                    origin=ctx.record_source,
                )
            else:
                methods: dict[str, Callable[..., object]] = {
                    "inspect_document": service.inspect_document,
                    "extract_document": service.extract_document,
                    "analyze_workbook": service.analyze_workbook,
                    "review_meeting_actions": service.review_meeting_actions,
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
        "analyze_workbook": _object(
            {
                "source": _ARTIFACT,
                "sheet": {"type": "string", "minLength": 1},
                "cell_range": {"type": "string", "minLength": 1},
                "group_by": {"type": "string", "minLength": 1},
                "value_column": {"type": "string", "minLength": 1},
                "compare_by": {"type": "string", "minLength": 1},
                "include_hidden_rows": {"type": "boolean"},
            },
            ["source", "sheet", "cell_range"],
        ),
        "review_meeting_actions": _object(
            {
                "notes": {"type": "string", "minLength": 1, "maxLength": 100_000},
                "candidates": {
                    "type": "array",
                    "maxItems": 500,
                    "items": _object({
                        "action": {"type": "string", "minLength": 1},
                        "evidence": {"type": "string", "minLength": 1},
                        "assignee": {"type": "string", "minLength": 1},
                        "due_date": {"type": "string", "format": "date"},
                        "suggested_due_date": {"type": "string", "format": "date"},
                    }, ["action", "evidence"]),
                },
            },
            ["notes", "candidates"],
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
        "office_job_request": {
            **_object(
                {
                    "request": {"type": "string", "minLength": 1},
                    "source": _ARTIFACT,
                    "format": {"type": "string", "enum": ["docx", "xlsx", "pptx", "pdf", "hwpx"]},
                    "content": {
                        "oneOf": [
                            _object({"paragraphs": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}}, ["paragraphs"]),
                            _object({"business_template": _object({
                                "name": {"type": "string", "enum": ["weekly_report", "meeting_notes", "work_proposal"]},
                                "version": {"type": "string", "enum": ["1.0"]},
                                "values": {"type": "object"},
                                "sources": {"type": "object", "additionalProperties": {"type": "string", "minLength": 1}},
                            }, ["name", "version", "values"])}, ["business_template"]),
                            _object({"sheets": {"type": "array", "minItems": 1, "items": {"type": "object"}}}, ["sheets"]),
                            _object({"slides": {"type": "array", "minItems": 1, "items": {"type": "object"}}}, ["slides"]),
                            _object({
                                "paragraphs": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                                "table": {"type": "array", "items": {"type": "array", "minItems": 1, "items": {"type": "string"}}},
                                "font": _ARTIFACT,
                            }, ["paragraphs", "font"]),
                        ]
                    },
                    "outcome": {"type": "string", "minLength": 1},
                    "operations": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 1000,
                        "items": PATCH_OPERATION_SCHEMA,
                    },
                    "destination": {"type": "string", "minLength": 1},
                    "overwrite_approved": {"type": "boolean"},
                },
                ["request", "outcome", "destination"],
            ),
            "oneOf": [
                {"required": ["source", "operations"]},
                {"required": ["format", "content"]},
            ],
        },
        "office_rollback_request": _object(
            {
                "job_id": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{32}$",
                },
            },
            ["job_id"],
        ),
    }
    return [
        Tool(name, f"Office Work OS: {name.replace('_', ' ')}.", schemas[name], _handler(name))
        for name in NAMES
    ]
