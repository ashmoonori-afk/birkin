"""Tests for tool interfaces, registry, and loader."""

from __future__ import annotations

from typing import Any

import pytest

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec
from birkin.tools.loader import load_tools
from birkin.tools.registry import ToolRegistry


class DummyTool(Tool):
    """Concrete tool for testing."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="dummy",
            description="A test tool",
            parameters=[
                ToolParameter(name="input", type="string", description="Input text"),
            ],
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        return ToolOutput(
            success=True,
            output=f"echo: {args.get('input', '')}",
        )


class TestToolSpec:
    def test_to_provider_schema(self):
        tool = DummyTool()
        schema = tool.to_provider_schema()
        assert schema["name"] == "dummy"
        assert "input" in schema["parameters"]["properties"]
        assert "input" in schema["parameters"]["required"]


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = DummyTool()
        reg.register(tool)
        assert reg.get("dummy") is tool

    def test_duplicate_raises(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(DummyTool())

    def test_unregister(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        reg.unregister("dummy")
        assert reg.get("dummy") is None

    def test_list_all(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        assert len(reg.list_all()) == 1

    def test_export_schemas(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        schemas = reg.export_schemas()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "dummy"

    def test_len(self):
        reg = ToolRegistry()
        assert len(reg) == 0
        reg.register(DummyTool())
        assert len(reg) == 1


class TestLoadTools:
    def test_loads_builtin_tools(self):
        from birkin.tools.registry import reset_registry

        reset_registry()
        tools = load_tools()
        names = {t.spec.name for t in tools}
        assert "shell" in names
        assert "web_search" in names
        assert "file_read" in names
        assert "file_write" in names
        reset_registry()
