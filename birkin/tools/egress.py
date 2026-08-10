"""Model-facing inspected egress capability."""

from __future__ import annotations

import json
from typing import Any

from .. import egress
from ._types import Tool, ToolContext, ToolResult


def _submit(tool_input: dict[str, Any], ctx: ToolContext) -> ToolResult:
    try:
        result = egress.submit_payload(
            ctx.cfg,
            str(tool_input.get("destination", "")),
            tool_input.get("payload", ""),
            str(tool_input.get("content_type", "")),
        )
    except egress.EgressError as exc:
        return ToolResult(f"Egress blocked: {exc}", is_error=True)
    return ToolResult(
        json.dumps(result, sort_keys=True),
        is_error=result.get("state") != "succeeded",
    )


def tools() -> list[Tool]:
    return [
        Tool(
            name="submit_payload",
            description=(
                "Send inspected JSON or text to a preconfigured trusted "
                "destination. URLs and authentication are never model input."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "destination": {"type": "string"},
                    "payload": {"type": "string"},
                    "content_type": {
                        "type": "string",
                        "enum": ["application/json", "text/plain"],
                    },
                },
                "required": ["destination", "payload", "content_type"],
                "additionalProperties": False,
            },
            fn=_submit,
        )
    ]
