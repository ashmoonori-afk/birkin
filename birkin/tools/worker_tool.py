"""Approval-only natural-language entry to Birkin's invokable workers."""

from __future__ import annotations

from typing import Any

from ._types import Tool, ToolContext, ToolResult


def _invoke(tool_input: dict[str, Any], ctx: ToolContext) -> ToolResult:
    from .. import approvals, worker_call

    try:
        call = worker_call.resolve(tool_input)
    except worker_call.WorkerCallError as exc:
        return ToolResult(f"Cannot invoke that worker: {exc}", is_error=True)

    status = approvals.propose(
        category=call.category,
        title=call.title(),
        description=call.description(),
        payload=call.payload(),
        cfg=ctx.cfg,
        origin=call.worker,
    )
    if status.get("auto"):
        ok = bool(status.get("ok"))
        return ToolResult(
            ("Started: " if ok else "Could not start: ")
            + str(status.get("result", "")),
            is_error=not ok,
        )
    return ToolResult(
        f"Queued {call.worker} for the user's approval (id {status['id']}). "
        "Nothing runs unless they approve it."
    )


def tools() -> list[Tool]:
    from .. import worker_call

    return [
        Tool(
            name="worker_invoke",
            description=(
                "Propose one structured worker request for explicit user approval. "
                "Choose only a request matching the worker's documented action. "
                "Workers: "
                + worker_call.describe_workers()
                + ". Questions and lookups remain normal turns."
            ),
            input_schema=worker_call.input_schema(),
            fn=_invoke,
        )
    ]
