"""Tool registry -- discovery and management."""

from __future__ import annotations

from birkin.tools.base import Tool


class ToolRegistry:
    """In-memory registry of available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool. Raises ValueError on duplicate name."""
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name!r}")
        self._tools[name] = tool

    def unregister(self, name: str) -> None:
        """Remove a tool by name."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def list_all(self) -> list[Tool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def export_schemas(self) -> list[dict]:
        """Export all tool schemas for provider tool_use."""
        return [t.to_provider_schema() for t in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)
