"""Tool adapter for the single typed Computer Use surface."""

from __future__ import annotations

import json

from .. import config
from ..computer_use.runtime import create_service
from ..computer_use.schema import ACTIONS, computer_use_schema
from ..computer_use.service import ComputerUseService
from ._types import Tool, ToolContext, ToolResult


def _service(ctx: ToolContext) -> ComputerUseService:
    current = ctx.computer_use_service
    if isinstance(current, ComputerUseService):
        return current
    service = create_service(
        artifact_root=config.birkin_home() / "computer-use" / "artifacts",
        policy_config=(
            ctx.cfg.get("computer_use")
            if isinstance(ctx.cfg.get("computer_use"), dict)
            else None
        ),
    )
    ctx.computer_use_service = service
    return service


def _computer_use(inp: dict[str, object], ctx: ToolContext) -> ToolResult:
    action = inp.get("action")
    if action not in ACTIONS:
        response = {
            "ok": False,
            "status": "refused",
            "effect": "suspected_noop",
            "refusal_code": "invalid_request",
            "mutation_dispatched": False,
        }
        return ToolResult(
            json.dumps(response, ensure_ascii=False, sort_keys=True),
            is_error=True,
        )
    response = _service(ctx).execute(dict(inp))
    return ToolResult(
        json.dumps(response, ensure_ascii=False, sort_keys=True),
        is_error=not bool(response.get("ok")),
    )


def tools() -> list[Tool]:
    return [
        Tool(
            name="computer_use",
            description=(
                "Observe and safely control one exact desktop app or window "
                "through generation-bound native accessibility state."
            ),
            input_schema=computer_use_schema(),
            fn=_computer_use,
        )
    ]
