"""Tests for birkin.mcp.registry."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from birkin.mcp.registry import MCPRegistry
from birkin.mcp.types import MCPServerConfig, MCPToolInfo


def _make_config(name: str = "srv") -> MCPServerConfig:
    return MCPServerConfig(name=name, command="echo")


def _make_tool_info(server: str, name: str) -> MCPToolInfo:
    return MCPToolInfo(
        server_name=server,
        name=name,
        description=f"{name} tool",
        input_schema={"type": "object"},
    )


class TestMCPRegistryAddRemove:
    @pytest.mark.asyncio
    async def test_add_server(self) -> None:
        registry = MCPRegistry()

        mock_client_instance = AsyncMock()
        mock_client_instance.name = "srv"
        mock_client_instance.connect = AsyncMock()
        mock_client_instance.list_tools = AsyncMock(
            return_value=[_make_tool_info("srv", "read"), _make_tool_info("srv", "write")]
        )
        mock_client_instance.disconnect = AsyncMock()

        with patch("birkin.mcp.registry.MCPClient", return_value=mock_client_instance):
            tools = await registry.add_server(_make_config("srv"))

        assert len(tools) == 2
        assert "srv" in registry.server_names
        assert len(registry) == 2

    @pytest.mark.asyncio
    async def test_add_duplicate_raises(self) -> None:
        registry = MCPRegistry()

        mock_client = AsyncMock()
        mock_client.name = "dup"
        mock_client.connect = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[])
        mock_client.disconnect = AsyncMock()

        with patch("birkin.mcp.registry.MCPClient", return_value=mock_client):
            await registry.add_server(_make_config("dup"))

            with pytest.raises(ValueError, match="already registered"):
                await registry.add_server(_make_config("dup"))

    @pytest.mark.asyncio
    async def test_remove_server(self) -> None:
        registry = MCPRegistry()

        mock_client = AsyncMock()
        mock_client.name = "rm"
        mock_client.connect = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[_make_tool_info("rm", "tool1")])
        mock_client.disconnect = AsyncMock()

        with patch("birkin.mcp.registry.MCPClient", return_value=mock_client):
            await registry.add_server(_make_config("rm"))
            assert len(registry) == 1

            await registry.remove_server("rm")
            assert len(registry) == 0
            assert "rm" not in registry.server_names
            mock_client.disconnect.assert_called_once()


class TestMCPRegistryToolLookup:
    @pytest.mark.asyncio
    async def test_find_tool(self) -> None:
        registry = MCPRegistry()

        mock_client = AsyncMock()
        mock_client.name = "s1"
        mock_client.connect = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[_make_tool_info("s1", "search")])

        with patch("birkin.mcp.registry.MCPClient", return_value=mock_client):
            await registry.add_server(_make_config("s1"))

        # Qualified lookup
        tool = registry.get_tool("s1/search")
        assert tool is not None
        assert tool.name == "search"

        # Unqualified lookup
        tool2 = registry.find_tool("search")
        assert tool2 is not None
        assert tool2.server_name == "s1"

        # Missing tool
        assert registry.find_tool("nonexistent") is None


class TestMCPRegistryLoadFromConfigs:
    @pytest.mark.asyncio
    async def test_skips_disabled(self) -> None:
        registry = MCPRegistry()

        disabled = MCPServerConfig(name="off", command="echo", enabled=False)
        enabled = _make_config("on")

        mock_client = AsyncMock()
        mock_client.name = "on"
        mock_client.connect = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[_make_tool_info("on", "t1")])

        with patch("birkin.mcp.registry.MCPClient", return_value=mock_client):
            tools = await registry.load_from_configs([disabled, enabled])

        assert len(tools) == 1
        assert "off" not in registry.server_names
        assert "on" in registry.server_names

    @pytest.mark.asyncio
    async def test_skips_failed_connection(self) -> None:
        registry = MCPRegistry()

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock(side_effect=RuntimeError("fail"))

        with patch("birkin.mcp.registry.MCPClient", return_value=mock_client):
            tools = await registry.load_from_configs([_make_config("bad")])

        assert len(tools) == 0
        assert len(registry) == 0


class TestMCPRegistryShutdown:
    @pytest.mark.asyncio
    async def test_shutdown(self) -> None:
        registry = MCPRegistry()

        mock_client = AsyncMock()
        mock_client.name = "s"
        mock_client.connect = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[])
        mock_client.disconnect = AsyncMock()

        with patch("birkin.mcp.registry.MCPClient", return_value=mock_client):
            await registry.add_server(_make_config("s"))

        await registry.shutdown()
        assert len(registry.server_names) == 0
        mock_client.disconnect.assert_called_once()
