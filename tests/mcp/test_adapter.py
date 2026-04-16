"""Tests for birkin.mcp.adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from birkin.mcp.adapter import MCPToolAdapter, _json_schema_to_params
from birkin.mcp.client import MCPClient
from birkin.mcp.types import MCPServerConfig, MCPToolCallResult, MCPToolInfo
from birkin.tools.base import Tool, ToolContext


def _make_info(
    server: str = "fs",
    name: str = "read_file",
    schema: dict | None = None,
) -> MCPToolInfo:
    return MCPToolInfo(
        server_name=server,
        name=name,
        description=f"{name} description",
        input_schema=schema or {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path"}},
            "required": ["path"],
        },
    )


def _make_client(name: str = "fs", connected: bool = True) -> MCPClient:
    client = MCPClient(MCPServerConfig(name=name, command="echo"))
    if connected:
        client._session = AsyncMock()  # fake connected state
    return client


class TestJsonSchemaToParams:
    def test_basic_conversion(self) -> None:
        params = _json_schema_to_params({
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "A path"},
                "recursive": {"type": "boolean", "description": "Recurse", "default": False},
            },
            "required": ["path"],
        })
        assert len(params) == 2
        assert params[0].name == "path"
        assert params[0].required is True
        assert params[1].name == "recursive"
        assert params[1].required is False
        assert params[1].default is False

    def test_enum_field(self) -> None:
        params = _json_schema_to_params({
            "type": "object",
            "properties": {
                "format": {"type": "string", "description": "Output format", "enum": ["json", "csv"]},
            },
        })
        assert params[0].enum == ["json", "csv"]

    def test_empty_schema(self) -> None:
        params = _json_schema_to_params({})
        assert params == []


class TestMCPToolAdapterSpec:
    def test_qualified_name(self) -> None:
        adapter = MCPToolAdapter(_make_info("myserver", "list_dir"), _make_client("myserver"))
        assert adapter.spec.name == "mcp__myserver__list_dir"

    def test_toolset_is_mcp(self) -> None:
        adapter = MCPToolAdapter(_make_info(), _make_client())
        assert adapter.spec.toolset == "mcp"

    def test_description_prefixed(self) -> None:
        adapter = MCPToolAdapter(_make_info(), _make_client())
        assert adapter.spec.description.startswith("[MCP:fs]")

    def test_is_tool_subclass(self) -> None:
        adapter = MCPToolAdapter(_make_info(), _make_client())
        assert isinstance(adapter, Tool)

    def test_mcp_tool_name(self) -> None:
        adapter = MCPToolAdapter(_make_info(name="write_file"), _make_client())
        assert adapter.mcp_tool_name == "write_file"


class TestMCPToolAdapterProviderSchema:
    def test_uses_original_input_schema(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "nested": {"type": "object", "properties": {"x": {"type": "integer"}}},
            },
        }
        adapter = MCPToolAdapter(_make_info(schema=schema), _make_client())
        exported = adapter.to_provider_schema()
        assert exported["parameters"] == schema
        assert exported["name"] == "mcp__fs__read_file"


class TestMCPToolAdapterExecute:
    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        client = _make_client()
        client.call_tool = AsyncMock(
            return_value=MCPToolCallResult(content="file contents here", is_error=False)
        )
        adapter = MCPToolAdapter(_make_info(), client)

        result = await adapter.execute({"path": "/tmp/test"}, ToolContext())
        assert result.success is True
        assert result.output == "file contents here"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_execute_error(self) -> None:
        client = _make_client()
        client.call_tool = AsyncMock(
            return_value=MCPToolCallResult(content="permission denied", is_error=True)
        )
        adapter = MCPToolAdapter(_make_info(), client)

        result = await adapter.execute({"path": "/secret"}, ToolContext())
        assert result.success is False
        assert result.error == "permission denied"

    @pytest.mark.asyncio
    async def test_execute_disconnected(self) -> None:
        client = _make_client(connected=False)
        adapter = MCPToolAdapter(_make_info(), client)

        result = await adapter.execute({"path": "/tmp"}, ToolContext())
        assert result.success is False
        assert "not connected" in result.error


class TestMCPToolAdapterAvailability:
    def test_available_when_connected(self) -> None:
        adapter = MCPToolAdapter(_make_info(), _make_client(connected=True))
        assert adapter.check_available() is True

    def test_unavailable_when_disconnected(self) -> None:
        adapter = MCPToolAdapter(_make_info(), _make_client(connected=False))
        assert adapter.check_available() is False
