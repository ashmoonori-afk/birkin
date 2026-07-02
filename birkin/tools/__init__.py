"""Tool system: registry, execution context, and the default toolset.

A *tool* is a small, well-bounded capability the agent can call. Each tool
declares an Anthropic-style ``input_schema`` and a handler
``fn(tool_input: dict, ctx: ToolContext) -> ToolResult``.

The registry exposes:
- ``specs()``  -> the tool list to send to the model
- ``execute(name, input)`` -> run a tool and return a ``ToolResult``

Tools never raise out of ``execute``; failures are returned as error results so
the agent can recover.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from ..llm import LLMClient


@dataclass
class ToolResult:
    content: str
    is_error: bool = False


@dataclass
class ToolContext:
    """Everything a tool might need, passed explicitly (no globals)."""
    cfg: dict[str, Any]
    client: LLMClient
    cwd: Path
    skills: Any = None          # skills.manager.SkillManager
    memory: Any = None          # memory.Memory
    depth: int = 0              # subagent recursion depth
    max_depth: int = 2
    emit: Optional[Callable[[str, dict[str, Any]], None]] = None


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[[dict[str, Any], ToolContext], ToolResult]


class ToolRegistry:
    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        return [{"name": t.name, "description": t.description,
                 "input_schema": t.input_schema} for t in self._tools.values()]

    def execute(self, name: str, tool_input: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(f"Unknown tool: {name!r}", is_error=True)
        try:
            return tool.fn(tool_input or {}, self.ctx)
        except Exception as exc:  # tools must never crash the agent loop
            return ToolResult(f"Tool {name!r} failed: {exc}", is_error=True)


def build_registry(ctx: ToolContext, *, include: Optional[set[str]] = None) -> ToolRegistry:
    """Assemble the default toolset.

    ``include`` optionally restricts which tool *groups* are registered
    (used to give subagents a scoped toolset). Groups:
    ``files``, ``shell``, ``web``, ``sessions``, ``skills``, ``memory``,
    ``subagent``.
    """
    from . import files, sessions, shell, web  # local imports avoid cycles
    from .subagent_tool import subagent_tools

    groups: dict[str, list[Tool]] = {
        "files": files.tools(),
        "shell": shell.tools(),
        "web": web.tools(),
        "sessions": sessions.tools(),
    }
    if ctx.skills is not None:
        groups["skills"] = ctx.skills.tools()
    if ctx.memory is not None:
        groups["memory"] = ctx.memory.tools()
    # Subagents may spawn further subagents only until max_depth.
    if ctx.depth < ctx.max_depth:
        groups["subagent"] = subagent_tools()

    disabled = set(ctx.cfg.get("disabled_tools", []) or [])
    registry = ToolRegistry(ctx)
    for group, tools_ in groups.items():
        if include is not None and group not in include:
            continue
        for t in tools_:
            if t.name in disabled:
                continue
            registry.register(t)
    return registry
