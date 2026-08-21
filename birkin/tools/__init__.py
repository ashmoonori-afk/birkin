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

from dataclasses import dataclass, replace
from typing import Any, Optional

from ..operation_approval import queue_operation
from ..operation_policy import (
    ApprovalRequiredError,
    diagnostic_block,
    permission_block,
)
from ..tool_attestations import ToolAttestationStore
from ..tool_effects import (
    EffectDecision,
    EffectLookup,
    EffectSnapshot,
    SnapshotEffectLookup,
    ToolOrigin,
)
from ._types import (
    ImageContentBlock as ImageContentBlock,
    ImageSource as ImageSource,
    TextContentBlock as TextContentBlock,
    Tool,
    ToolContent,
    ToolContext as ToolContext,
    ToolResult as ToolResult,
    content_text,
)


@dataclass(frozen=True, slots=True)
class _RegisteredTool:
    tool: Tool
    origin: ToolOrigin
    decision: EffectDecision


class ToolRegistry:
    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self._effects: EffectLookup = SnapshotEffectLookup(
            EffectSnapshot("missing", ()))
        self._tools: dict[str, _RegisteredTool] = {}
        self._blocked: dict[str, str] = {}

    def register(self, tool: Tool) -> None:
        origin = tool.origin
        registered = self._tools.get(tool.name)
        if (
            registered is not None
            and registered.origin.kind == "native"
            and origin.kind == "plugin"
        ):
            return
        self._tools[tool.name] = _RegisteredTool(
            tool, origin, self._effects.decision_for(origin, tool.name))

    def refresh_effects(self) -> EffectSnapshot:
        snapshot = ToolAttestationStore().load()
        effects = SnapshotEffectLookup(snapshot)
        self._effects = effects
        self._tools = {
            name: replace(
                registered,
                decision=effects.decision_for(registered.origin, name),
            )
            for name, registered in self._tools.items()
        }
        return snapshot

    def can_parallelize(self, name: str) -> bool:
        registered = self._tools.get(name)
        return registered is not None and registered.decision.parallel_safe

    def register_blocked(self, tool: Tool, reason: str) -> None:
        self._blocked[tool.name] = reason

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": registered.tool.name,
                "description": registered.tool.description,
                "input_schema": registered.tool.input_schema,
            }
            for registered in self._tools.values()
        ]

    def execute(self, name: str, tool_input: dict[str, Any]) -> ToolResult:
        registered = self._tools.get(name)
        if registered is None:
            reason = self._blocked.get(name)
            if reason is not None:
                return queue_operation(
                    name,
                    tool_input,
                    self.ctx,
                    ApprovalRequiredError("tool_policy", reason),
                )
            return ToolResult(f"Unknown tool: {name!r}", is_error=True)
        tool = registered.tool
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
            result = queue_operation(name, tool_input, self.ctx, block)
        except OSError as exc:
            block = permission_block(exc)
            result = (
                queue_operation(name, tool_input, self.ctx, block)
                if block is not None
                else ToolResult(f"Tool {name!r} failed: {exc}", is_error=True)
            )
        except Exception as exc:  # tools must never crash the agent loop
            result = ToolResult(f"Tool {name!r} failed: {exc}", is_error=True)
        if self.ctx.checkpoints is not None:
            from .. import checkpoints
            try:
                checkpoints.postflight(self.ctx, name, failed=result.is_error)
            except Exception as exc:
                return ToolResult(
                    f"Checkpoint failed after {name!r}: {exc}", is_error=True)
        if result.is_error:
            block = diagnostic_block(
                content_text(result.content),
                tool=name,
                command=str(tool_input.get("command", "")),
            )
            if block is not None:
                return queue_operation(name, tool_input, self.ctx, block)
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


def build_tool_groups(ctx: ToolContext) -> dict[str, list[Tool]]:
    """Build the canonical ordered tool-group inventory."""
    from .. import browser
    from . import (citations, computer_use, desktop, documents, egress, files, market,
                   sessions, shell, vision, web)  # local: avoid cycles
    from .subagent_tool import subagent_tools

    groups: dict[str, list[Tool]] = {
        "files": files.tools(),
        "shell": shell.tools(),
        "web": web.tools() + market.tools() + citations.tools(),
        "sessions": sessions.tools(),
        "vision": vision.tools(),
        "browser": browser.tools(),
        "egress": egress.tools(),
        "documents": documents.tools(),
    }
    from ..plugin_runtime import load_agent_tools, registry_roots
    plugin_project, plugin_team = registry_roots(ctx.cwd)
    groups["plugins"] = load_agent_tools(plugin_project, plugin_team)
    if ctx.cfg.get("desktop_tools") is True:
        groups["desktop"] = desktop.tools()
        computer_use_config = ctx.cfg.get("computer_use")
        if (
            isinstance(computer_use_config, dict)
            and computer_use_config.get("enabled") is True
        ):
            groups["desktop"] += computer_use.tools()
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
    # Natural-language door to the workers. Proposal-only: the tool queues an
    # approval, it never starts a worker.
    if ctx.cfg.get("worker_call_auto", True):
        from . import worker_tool
        groups["worker"] = worker_tool.tools()
    # Subagents may spawn further subagents only until max_depth.
    if ctx.depth < ctx.max_depth:
        groups["subagent"] = subagent_tools()
    return groups


def build_registry(
    ctx: ToolContext,
    *,
    include: Optional[set[str]] = None,
    approval_replay: bool = False,
) -> ToolRegistry:
    """Assemble the default toolset from canonical group metadata."""
    groups = build_tool_groups(ctx)

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
