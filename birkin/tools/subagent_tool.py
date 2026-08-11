"""The ``spawn_subagent`` tool.

Delegates a self-contained sub-task to an isolated agent (fresh conversation,
scoped toolset). The actual runner lives in ``birkin.subagent`` and is imported
lazily to avoid an import cycle (tools <- subagent <- tools).
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from ._types import Tool, ToolContext, ToolResult


def _spawn_subagent(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
    task = inp.get("task", "").strip()
    if not task:
        return ToolResult("Missing 'task'", is_error=True)
    if ctx.depth >= ctx.max_depth:
        return ToolResult("Subagent depth limit reached", is_error=True)
    if ctx.subagent_approval_required and not ctx.approved_work:
        return ToolResult(
            "Subagent execution requires an approved Telegram workflow.",
            is_error=True,
        )

    run_subagent = import_module("birkin.subagent").run_subagent
    skills = inp.get("skills") or None
    max_turns = int(inp.get("max_turns", 12))
    result = run_subagent(task, ctx, skill_names=skills, max_turns=max_turns,
                          detach=bool(inp.get("detach", False)))
    return ToolResult(result)


def subagent_tools() -> list[Tool]:
    return [
        Tool(
            name="spawn_subagent",
            description="Delegate a focused, self-contained sub-task to an "
                        "isolated subagent and get back its result. Use for "
                        "parallelizable or context-heavy work (research, a "
                        "refactor, an analysis) so the main conversation stays "
                        "clean. Give the subagent a complete brief — it cannot "
                        "see this conversation. Set detach=true to keep working "
                        "while it runs; the caller follows it with /attach.",
            input_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string",
                             "description": "Complete, self-contained instructions"},
                    "skills": {"type": "array", "items": {"type": "string"},
                               "description": "Optional skill names to preload"},
                    "max_turns": {"type": "integer",
                                  "description": "Tool-turn budget (default 12)"},
                    "detach": {"type": "boolean",
                               "description": "Run in the background and return "
                                              "the run id immediately instead of "
                                              "blocking until it finishes"},
                },
                "required": ["task"],
            },
            fn=_spawn_subagent,
        ),
    ]
