"""Natural-language entry to the workers: the model names one, a human approves.

Workers used to be reachable only from the CLI, so asking for one in chat did
nothing. This tool is the door, and it is deliberately the same door
``companion_propose`` uses: it can only queue a *candidate* into the approval
inbox (``birkin review`` / the gateway buttons). It cannot start a worker, and
:mod:`birkin.worker_call` refuses any name that is not a real, implemented,
non-reserved worker before the request ever reaches the queue.
"""

from __future__ import annotations

from typing import Any

from ._types import Tool, ToolContext, ToolResult


def _invoke(tool_input: dict[str, Any], ctx: ToolContext) -> ToolResult:
    from .. import approvals, worker_call
    try:
        call = worker_call.resolve(tool_input.get("worker"),
                                   tool_input.get("task", ""))
    except worker_call.WorkerCallError as exc:
        return ToolResult(f"Cannot invoke that worker: {exc}", is_error=True)

    status = approvals.propose(
        category="operation",
        title=call.title(),
        description=f"{call.task}\n\nRuns: {' '.join(call.argv())}",
        payload=call.payload(),
        cfg=ctx.cfg,
        origin=call.worker)
    if status.get("auto"):
        ok = bool(status.get("ok"))
        return ToolResult(("Started: " if ok else "Could not start: ")
                          + str(status.get("result", "")), is_error=not ok)
    return ToolResult(
        f"Queued {call.worker} for the user's approval (id {status['id']}). "
        f"Nothing runs unless they approve it.")


def tools() -> list[Tool]:
    from .. import worker_call
    return [Tool(
        name="worker_invoke",
        description=(
            "Ask for one of birkin's workers when the user requests, in their "
            "own words, work that worker owns. NOT executed now — it goes to "
            "the user's approval queue. Workers: "
            + worker_call.describe_workers()
            + ". Use this only when the request is squarely a worker's job; a "
              "question, a lookup, or anything you can simply answer is a "
              "normal turn, so answer it instead."),
        input_schema={"type": "object", "properties": {
            "worker": {"type": "string",
                       "enum": list(worker_call.invokable_workers()),
                       "description": "which worker should run"},
            "task": {"type": "string",
                     "description": "what the user actually asked for, in "
                                    "their words"}},
            "required": ["worker", "task"]},
        fn=_invoke)]
