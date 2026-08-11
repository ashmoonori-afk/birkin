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

from typing import Any, Optional

from ..operation_approval import queue_operation
from ..operation_policy import (
    ApprovalRequiredError,
    diagnostic_block,
    permission_block,
)
from ._types import Tool, ToolContext, ToolResult


class ToolRegistry:
    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self._tools: dict[str, Tool] = {}
        self._blocked: dict[str, str] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def register_blocked(self, tool: Tool, reason: str) -> None:
        self._blocked[tool.name] = reason

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        return [{"name": t.name, "description": t.description,
                 "input_schema": t.input_schema} for t in self._tools.values()]

    def execute(self, name: str, tool_input: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            reason = self._blocked.get(name)
            if reason is not None:
                return queue_operation(
                    name,
                    tool_input,
                    self.ctx,
                    ApprovalRequiredError("tool_policy", reason),
                )
            return ToolResult(f"Unknown tool: {name!r}", is_error=True)
        if self.ctx.hooks is not None:
            # A blocking hook's message becomes the tool result, so the
            # model sees why it was refused and can choose another path.
            blocked = self.ctx.hooks.pre_tool(name, tool_input or {})
            if blocked:
                return queue_operation(
                    name,
                    tool_input,
                    self.ctx,
                    ApprovalRequiredError("hook_policy", blocked),
                )
        if self.ctx.checkpoints is not None:
            from .. import checkpoints
            try:
                checkpoints.preflight(self.ctx, name, tool_input or {})
            except Exception as exc:
                return ToolResult(
                    f"Checkpoint failed before {name!r}: {exc}",
                    is_error=True)
        try:
            result = tool.fn(tool_input or {}, self.ctx)
        except ApprovalRequiredError as block:
            return queue_operation(name, tool_input, self.ctx, block)
        except OSError as exc:
            block = permission_block(exc)
            if block is not None:
                return queue_operation(name, tool_input, self.ctx, block)
            return ToolResult(f"Tool {name!r} failed: {exc}", is_error=True)
        except Exception as exc:  # tools must never crash the agent loop
            return ToolResult(f"Tool {name!r} failed: {exc}", is_error=True)
        if result.is_error:
            block = diagnostic_block(
                result.content,
                tool=name,
                command=str(tool_input.get("command", "")),
            )
            if block is not None:
                return queue_operation(name, tool_input, self.ctx, block)
        if self.ctx.hooks is not None:
            try:
                self.ctx.hooks.post_tool(name, tool_input or {},
                                         result.content, result.is_error)
            except Exception:
                pass          # observers must not break the loop
        # The single choke point every native tool call passes through, so
        # oversized output is handled once rather than in each tool.
        from ..redact import redact_tool_output
        from .spill import maybe_spill
        # Mask BEFORE spilling: a secret must be absent from the file written
        # to disk too, not merely from the text the model is shown.
        content = redact_tool_output(result.content, self.ctx.cfg)
        content = maybe_spill(content, name, self.ctx.cfg)
        return result if content is result.content \
            else ToolResult(content, result.is_error)


def build_registry(
    ctx: ToolContext,
    *,
    include: Optional[set[str]] = None,
    approval_replay: bool = False,
) -> ToolRegistry:
    """Assemble the default toolset.

    ``include`` optionally restricts which tool *groups* are registered
    (used to give subagents a scoped toolset). Groups:
    ``files``, ``shell``, ``web``, ``sessions``, ``skills``, ``memory``,
    ``egress``, ``companion``, ``subagent``.
    """
    from . import (citations, egress, files, market, sessions,  # local: avoid cycles
                   shell, web)
    from .subagent_tool import subagent_tools

    groups: dict[str, list[Tool]] = {
        "files": files.tools(),
        "shell": shell.tools(),
        "web": web.tools() + market.tools() + citations.tools(),
        "sessions": sessions.tools(),
        "egress": egress.tools(),
    }
    if ctx.skills is not None:
        groups["skills"] = ctx.skills.tools()
    if ctx.memory is not None:
        groups["memory"] = ctx.memory.tools()
    # Companion is opt-in; don't spend prompt tokens on the tool until the
    # user has bound a context (path checked directly — companion_dir() would
    # mkdir as a side effect).
    from .. import config as _config
    if (_config.birkin_home() / "companion" / "state.json").is_file():
        from . import companion_tool
        groups["companion"] = companion_tool.tools()
    # Subagents may spawn further subagents only until max_depth.
    if ctx.depth < ctx.max_depth:
        groups["subagent"] = subagent_tools()

    disabled = (
        set()
        if approval_replay
        else set(ctx.cfg.get("disabled_tools", []) or [])
    )
    egress_cfg = ctx.cfg.get("egress")
    if not approval_replay and isinstance(egress_cfg, dict):
        if egress_cfg.get("enabled") is False:
            disabled.add("egress")
        elif (egress_cfg.get("enabled") is True
                and egress_cfg.get("enforced") is True):
            disabled.update({"shell", "subagent"})
    # Per-model engine preset (senpi-style): fast/local models drop whole
    # groups (e.g. web, subagent). Entries match a group OR a tool name.
    from .. import presets
    if not approval_replay:
        disabled |= presets.deny_tools(ctx.cfg.get("model"), ctx.cfg)
    registry = ToolRegistry(ctx)
    for group, tools_ in groups.items():
        if include is not None and group not in include:
            continue
        if group in disabled:
            for tool in tools_:
                registry.register_blocked(
                    tool,
                    f"Tool group {group!r} is disabled by Birkin policy",
                )
            continue
        for tool in tools_:
            if tool.name in disabled:
                registry.register_blocked(
                    tool,
                    f"Tool {tool.name!r} is disabled by Birkin policy",
                )
                continue
            registry.register(tool)
    return registry
