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

from ._types import (
    ImageContentBlock as ImageContentBlock,
    ImageSource as ImageSource,
    TextContentBlock as TextContentBlock,
    Tool,
    ToolContent,
    ToolContext,
    ToolResult,
    content_text,
)


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
        if self.ctx.hooks is not None:
            # A blocking hook's message becomes the tool result, so the
            # model sees why it was refused and can choose another path.
            blocked = self.ctx.hooks.pre_tool(name, tool_input or {})
            if blocked:
                return ToolResult(blocked, is_error=True)
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
        except Exception as exc:  # tools must never crash the agent loop
            return ToolResult(f"Tool {name!r} failed: {exc}", is_error=True)
        if self.ctx.hooks is not None:
            try:
                self.ctx.hooks.post_tool(
                    name, tool_input or {}, content_text(result.content),
                    result.is_error)
            except Exception:
                pass          # observers must not break the loop
        # The single choke point every native tool call passes through, so
        # oversized output is handled once rather than in each tool.
        from ..redact import redact_tool_output
        from .spill import maybe_spill
        # Mask BEFORE spilling: a secret must be absent from the file written
        # to disk too, not merely from the text the model is shown.
        if isinstance(result.content, str):
            content: ToolContent = redact_tool_output(
                result.content, self.ctx.cfg)
            content = maybe_spill(content, name, self.ctx.cfg)
        else:
            content = [
                {**block, "text": redact_tool_output(block["text"], self.ctx.cfg)}
                if block["type"] == "text" else block
                for block in result.content
            ]
        return result if content is result.content \
            else ToolResult(content, result.is_error)


def build_registry(ctx: ToolContext, *, include: Optional[set[str]] = None) -> ToolRegistry:
    """Assemble the default toolset.

    ``include`` optionally restricts which tool *groups* are registered
    (used to give subagents a scoped toolset). Groups:
    ``files``, ``shell``, ``web``, ``sessions``, ``skills``, ``memory``,
    ``vision``, ``desktop``, ``egress``, ``companion``, ``subagent``.
    """
    from . import (citations, desktop, egress, files, market,  # local: avoid cycles
                   sessions, shell, vision, web)
    from .subagent_tool import subagent_tools

    groups: dict[str, list[Tool]] = {
        "files": files.tools(),
        "shell": shell.tools(),
        "web": web.tools() + market.tools() + citations.tools(),
        "sessions": sessions.tools(),
        "vision": vision.tools(),
        "egress": egress.tools(),
    }
    if ctx.cfg.get("desktop_tools") is True:
        groups["desktop"] = desktop.tools()
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

    disabled = set(ctx.cfg.get("disabled_tools", []) or [])
    egress_cfg = ctx.cfg.get("egress")
    if isinstance(egress_cfg, dict):
        if egress_cfg.get("enabled") is False:
            disabled.add("egress")
        elif (egress_cfg.get("enabled") is True
                and egress_cfg.get("enforced") is True):
            disabled.update({"shell", "subagent"})
    # Per-model engine preset (senpi-style): fast/local models drop whole
    # groups (e.g. web, subagent). Entries match a group OR a tool name.
    from .. import presets
    disabled |= presets.deny_tools(ctx.cfg.get("model"), ctx.cfg)
    registry = ToolRegistry(ctx)
    for group, tools_ in groups.items():
        if include is not None and group not in include:
            continue
        if group in disabled:
            continue
        for t in tools_:
            if t.name in disabled:
                continue
            registry.register(t)
    return registry
