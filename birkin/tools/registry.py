"""Tool registry -- discovery and management."""

from __future__ import annotations

import threading
from typing import Any, Optional

from birkin.tools.base import Tool, ToolContext, ToolOutput


class ToolRegistry:
    """Thread-safe in-memory registry of available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._lock = threading.Lock()

    def register(self, tool: Tool) -> None:
        """Register a tool. Raises ValueError on duplicate name."""
        with self._lock:
            name = tool.spec.name
            if name in self._tools:
                raise ValueError(f"Tool already registered: {name!r}")
            self._tools[name] = tool

    def unregister(self, name: str) -> None:
        """Remove a tool by name."""
        with self._lock:
            self._tools.pop(name, None)

    def get(self, name: str) -> Optional[Tool]:
        """Look up a tool by name."""
        with self._lock:
            return self._tools.get(name)

    def list_all(self, available_only: bool = False) -> list[Tool]:
        """Return all registered tools.

        Args:
            available_only: If True, only return tools where check_available() is True.
        """
        with self._lock:
            tools = list(self._tools.values())
        if available_only:
            tools = [t for t in tools if t.check_available()]
        return tools

    def list_toolsets(self) -> list[str]:
        """Return all unique toolsets in the registry."""
        with self._lock:
            return list(set(t.spec.toolset for t in self._tools.values()))

    def list_by_toolset(self, toolset: str, available_only: bool = False) -> list[Tool]:
        """Return tools in a specific toolset.

        Args:
            toolset: Toolset name to filter by.
            available_only: If True, only return available tools.
        """
        with self._lock:
            tools = [t for t in self._tools.values() if t.spec.toolset == toolset]
        if available_only:
            tools = [t for t in tools if t.check_available()]
        return tools

    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: Optional[ToolContext] = None,
    ) -> ToolOutput:
        """Execute a tool by name.

        Args:
            tool_name: Name of the tool to execute.
            args: Arguments to pass to the tool.
            context: Execution context (optional).

        Returns:
            ToolOutput from the tool execution.

        Raises:
            ValueError: If tool not found.
        """
        tool = self.get(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name!r}")

        if context is None:
            context = ToolContext()

        try:
            result = await tool.execute(args, context)
            return result
        except Exception as e:
            return ToolOutput(
                success=False,
                output="",
                error=str(e),
            )

    def export_schemas(self, available_only: bool = True) -> list[dict]:
        """Export tool schemas for provider tool_use.

        Args:
            available_only: If True, only export schemas for available tools.

        Returns:
            List of provider-compatible tool schemas.
        """
        tools = self.list_all(available_only=available_only)
        return [t.to_provider_schema() for t in tools]

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolRegistry({len(self)} tools)"


# Module-level singleton
_registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    """Get the module-level singleton registry."""
    return _registry


def reset_registry() -> None:
    """Reset for testing — clears all registered tools."""
    global _registry  # noqa: PLW0603
    _registry = ToolRegistry()
