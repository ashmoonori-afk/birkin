"""Tests for birkin.mcp.client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from birkin.mcp.client import MCPClient
from birkin.mcp.types import MCPServerConfig, MCPToolInfo


def _make_config(name: str = "test") -> MCPServerConfig:
    return MCPServerConfig(name=name, command="echo", args=["hello"])


def _mock_mcp_tool(name: str = "echo", description: str = "Echo tool") -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = {"type": "object", "properties": {"msg": {"type": "string"}}}
    return tool


class TestMCPClientConstruction:
    def test_initial_state(self) -> None:
        client = MCPClient(_make_config("myserver"))
        assert client.name == "myserver"
        assert client.connected is False

    def test_ensure_connected_raises(self) -> None:
        client = MCPClient(_make_config())
        with pytest.raises(RuntimeError, match="not connected"):
            client._ensure_connected()


class TestMCPClientListTools:
    @pytest.mark.asyncio
    async def test_list_tools(self) -> None:
        client = MCPClient(_make_config("srv"))

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.tools = [_mock_mcp_tool("read"), _mock_mcp_tool("write")]
        mock_session.list_tools.return_value = mock_result

        # Inject mock session directly
        client._session = mock_session

        tools = await client.list_tools()
        assert len(tools) == 2
        assert tools[0].name == "read"
        assert tools[0].server_name == "srv"
        assert tools[1].name == "write"
        assert isinstance(tools[0], MCPToolInfo)


class TestMCPClientCallTool:
    @pytest.mark.asyncio
    async def test_call_tool_success(self) -> None:
        client = MCPClient(_make_config())

        mock_session = AsyncMock()
        mock_text = MagicMock()
        mock_text.text = "hello world"
        # Make isinstance check work for TextContent
        mock_text.__class__ = type("TextContent", (), {})

        mock_call_result = MagicMock()
        mock_call_result.content = [mock_text]
        mock_call_result.isError = False
        mock_session.call_tool.return_value = mock_call_result

        client._session = mock_session

        # Patch isinstance check for TextContent
        with patch("birkin.mcp.client.TextContent", type(mock_text)):
            result = await client.call_tool("echo", {"msg": "hi"})

        assert result.is_error is False
        assert "hello world" in result.content

    @pytest.mark.asyncio
    async def test_call_tool_error(self) -> None:
        client = MCPClient(_make_config())

        mock_session = AsyncMock()
        mock_session.call_tool.side_effect = RuntimeError("connection lost")
        client._session = mock_session

        result = await client.call_tool("bad_tool", {})
        assert result.is_error is True
        assert "connection lost" in result.content


class TestMCPClientContextManager:
    @pytest.mark.asyncio
    async def test_connect_disconnect(self) -> None:
        client = MCPClient(_make_config())

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("birkin.mcp.client.open_session", return_value=mock_ctx):
            await client.connect()
            assert client.connected is True

            await client.disconnect()
            assert client.connected is False
