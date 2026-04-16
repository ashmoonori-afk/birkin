"""Tests for birkin.mcp.server."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp.types import CallToolRequest, ListToolsRequest

from birkin.mcp.server import create_mcp_server
from birkin.memory.wiki import WikiMemory
from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


class EchoTool(Tool):
    """Minimal tool for testing."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="echo",
            description="Echo the input message",
            parameters=[
                ToolParameter(name="message", type="string", description="Message to echo"),
            ],
        )

    async def execute(self, args: dict, context: ToolContext) -> ToolOutput:
        return ToolOutput(success=True, output=args.get("message", ""))


class FailTool(Tool):
    """Tool that always fails."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="fail_tool", description="Always fails")

    async def execute(self, args: dict, context: ToolContext) -> ToolOutput:
        return ToolOutput(success=False, output="", error="intentional failure")


@pytest.fixture
def echo_tool() -> EchoTool:
    return EchoTool()


@pytest.fixture
def wiki_memory(tmp_path: Path) -> WikiMemory:
    mem = WikiMemory(root=tmp_path / "memory")
    mem.init()
    mem.ingest("concepts", "python-asyncio", "# Python Asyncio\n\nConcurrency with async/await.")
    mem.ingest("entities", "birkin", "# Birkin\n\nAI agent platform.")
    return mem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _list_tools(server):
    handler = server.request_handlers[ListToolsRequest]
    req = ListToolsRequest(method="tools/list")
    result = await handler(req)
    return result.root.tools


async def _call_tool(server, name: str, arguments: dict | None = None):
    handler = server.request_handlers[CallToolRequest]
    req = CallToolRequest(method="tools/call", params={"name": name, "arguments": arguments or {}})
    result = await handler(req)
    return result.root.content


# ---------------------------------------------------------------------------
# Tool tests
# ---------------------------------------------------------------------------


class TestServerListTools:
    @pytest.mark.asyncio
    async def test_list_provided_tools(self, echo_tool: EchoTool) -> None:
        server = create_mcp_server(tools=[echo_tool])
        tools = await _list_tools(server)
        assert len(tools) == 1
        assert tools[0].name == "echo"
        assert tools[0].description == "Echo the input message"
        assert "message" in tools[0].inputSchema["properties"]

    @pytest.mark.asyncio
    async def test_list_default_builtins(self) -> None:
        server = create_mcp_server()
        tools = await _list_tools(server)
        names = [t.name for t in tools]
        assert "shell" in names
        assert "file_read" in names
        assert "file_write" in names
        assert "web_search" in names

    @pytest.mark.asyncio
    async def test_list_multiple_tools(self, echo_tool: EchoTool) -> None:
        server = create_mcp_server(tools=[echo_tool, FailTool()])
        tools = await _list_tools(server)
        assert len(tools) == 2


class TestServerCallTool:
    @pytest.mark.asyncio
    async def test_call_tool_success(self, echo_tool: EchoTool) -> None:
        server = create_mcp_server(tools=[echo_tool])
        content = await _call_tool(server, "echo", {"message": "hello world"})
        assert len(content) == 1
        assert content[0].text == "hello world"

    @pytest.mark.asyncio
    async def test_call_tool_not_found(self, echo_tool: EchoTool) -> None:
        server = create_mcp_server(tools=[echo_tool])
        content = await _call_tool(server, "nonexistent", {})
        assert "not found" in content[0].text.lower()

    @pytest.mark.asyncio
    async def test_call_tool_error_result(self) -> None:
        server = create_mcp_server(tools=[FailTool()])
        content = await _call_tool(server, "fail_tool", {})
        assert "intentional failure" in content[0].text

    @pytest.mark.asyncio
    async def test_call_tool_no_arguments(self, echo_tool: EchoTool) -> None:
        server = create_mcp_server(tools=[echo_tool])
        content = await _call_tool(server, "echo", None)
        # MCP server validates inputSchema — missing required 'message' returns validation error
        assert len(content) >= 1


# ---------------------------------------------------------------------------
# Resource tests (wiki memory)
# ---------------------------------------------------------------------------


class TestServerResources:
    @pytest.mark.asyncio
    async def test_list_resources(self, wiki_memory: WikiMemory) -> None:
        from mcp.types import ListResourcesRequest

        server = create_mcp_server(tools=[], memory=wiki_memory)
        handler = server.request_handlers[ListResourcesRequest]
        req = ListResourcesRequest(method="resources/list")
        result = await handler(req)
        resources = result.root.resources
        uris = [str(r.uri) for r in resources]
        assert any("concepts/python-asyncio" in u for u in uris)
        assert any("entities/birkin" in u for u in uris)

    @pytest.mark.asyncio
    async def test_read_resource(self, wiki_memory: WikiMemory) -> None:
        from mcp.types import ReadResourceRequest

        server = create_mcp_server(tools=[], memory=wiki_memory)
        handler = server.request_handlers[ReadResourceRequest]
        req = ReadResourceRequest(
            method="resources/read",
            params={"uri": "birkin://memory/concepts/python-asyncio"},
        )
        result = await handler(req)
        contents = result.root.contents
        assert len(contents) >= 1
        # Server returns TextResourceContents wrapped by SDK
        first = contents[0]
        text = first.text if hasattr(first, "text") else str(first)
        assert "Python Asyncio" in text

    @pytest.mark.asyncio
    async def test_read_resource_not_found(self, wiki_memory: WikiMemory) -> None:
        from mcp.types import ReadResourceRequest

        server = create_mcp_server(tools=[], memory=wiki_memory)
        handler = server.request_handlers[ReadResourceRequest]
        req = ReadResourceRequest(
            method="resources/read",
            params={"uri": "birkin://memory/concepts/nonexistent"},
        )
        with pytest.raises(ValueError, match="not found"):
            await handler(req)

    @pytest.mark.asyncio
    async def test_read_resource_invalid_uri(self, wiki_memory: WikiMemory) -> None:
        from mcp.types import ReadResourceRequest

        server = create_mcp_server(tools=[], memory=wiki_memory)
        handler = server.request_handlers[ReadResourceRequest]
        req = ReadResourceRequest(
            method="resources/read",
            params={"uri": "http://example.com/bad"},
        )
        with pytest.raises(ValueError, match="Unknown resource"):
            await handler(req)

    def test_no_resources_without_memory(self) -> None:
        from mcp.types import ListResourcesRequest

        server = create_mcp_server(tools=[])
        assert ListResourcesRequest not in server.request_handlers


# ---------------------------------------------------------------------------
# CLI parser test
# ---------------------------------------------------------------------------


class TestMCPCLI:
    def test_parser_mcp_serve(self) -> None:
        from birkin.cli.main import create_parser

        parser = create_parser()
        args = parser.parse_args(["mcp", "serve"])
        assert args.command == "mcp"
        assert args.mcp_command == "serve"
        assert args.no_tools is False

    def test_parser_mcp_serve_no_tools(self) -> None:
        from birkin.cli.main import create_parser

        parser = create_parser()
        args = parser.parse_args(["mcp", "serve", "--no-tools"])
        assert args.no_tools is True

    def test_parser_mcp_serve_memory_dir(self) -> None:
        from birkin.cli.main import create_parser

        parser = create_parser()
        args = parser.parse_args(["mcp", "serve", "--memory-dir", "/tmp/mem"])
        assert args.memory_dir == "/tmp/mem"
