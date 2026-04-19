"""MCP server — expose Birkin tools and memory as MCP.

Allows external MCP clients (Claude Code, Cursor, etc.) to use Birkin's
built-in tools and query its wiki memory via the Model Context Protocol.

Usage::

    birkin mcp serve          # stdio transport (for IDE integration)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    TextContent,
)
from mcp.types import (
    Tool as MCPTool,
)

from birkin.tools.base import Tool, ToolContext, ToolOutput

if TYPE_CHECKING:
    from birkin.memory.wiki import WikiMemory

logger = logging.getLogger(__name__)


def create_mcp_server(
    *,
    name: str = "birkin",
    tools: list[Tool] | None = None,
    memory: WikiMemory | None = None,
) -> Server:
    """Create and configure a Birkin MCP server.

    Args:
        name: Server name advertised to clients.
        tools: Tools to expose. Defaults to all built-in tools.
        memory: WikiMemory instance for resource exposure. Optional.

    Returns:
        Configured mcp Server ready to run.
    """
    server = Server(name)

    # Instantiate built-in tools if none provided
    if tools is None:
        from birkin.tools.builtins import ALL_BUILTIN_TOOLS

        tools = [cls() for cls in ALL_BUILTIN_TOOLS]

    tool_registry: dict[str, Tool] = {t.spec.name: t for t in tools}

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @server.list_tools()
    async def handle_list_tools() -> list[MCPTool]:
        result: list[MCPTool] = []
        for tool in tools:
            spec = tool.spec
            input_schema = {
                "type": "object",
                "properties": {
                    p.name: {
                        "type": p.type,
                        "description": p.description,
                        **({"enum": p.enum} if p.enum else {}),
                        **({"default": p.default} if p.default is not None else {}),
                    }
                    for p in spec.parameters
                },
                "required": [p.name for p in spec.parameters if p.required],
            }
            result.append(
                MCPTool(
                    name=spec.name,
                    description=spec.description,
                    inputSchema=input_schema,
                )
            )
        return result

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        tool = tool_registry.get(name)
        if tool is None:
            return [TextContent(type="text", text=f"Tool not found: {name}")]

        ctx = ToolContext()
        try:
            result: ToolOutput = await tool.execute(args=arguments or {}, context=ctx)
            text = result.output if result.success else (result.error or "Unknown error")
            return [TextContent(type="text", text=text)]
        except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
            logger.error("MCP tool %r execution failed: %s", name, exc)
            return [TextContent(type="text", text=f"Tool execution failed: {exc}")]

    # ------------------------------------------------------------------
    # Resources (wiki memory)
    # ------------------------------------------------------------------

    if memory is not None:

        @server.list_resources()
        async def handle_list_resources() -> list[Resource]:
            pages = memory.list_pages()
            resources: list[Resource] = []
            for page in pages:
                uri = f"birkin://memory/{page['category']}/{page['slug']}"
                resources.append(
                    Resource(
                        uri=uri,
                        name=f"{page['category']}/{page['slug']}",
                        description=f"Wiki page: {page['category']}/{page['slug']}",
                        mimeType="text/markdown",
                    )
                )
            return resources

        @server.read_resource()
        async def handle_read_resource(uri: str) -> list[ReadResourceContents]:
            # Parse birkin://memory/{category}/{slug}
            prefix = "birkin://memory/"
            uri_str = str(uri)
            if not uri_str.startswith(prefix):
                raise ValueError(f"Unknown resource URI: {uri}")

            path_part = uri_str[len(prefix) :]
            parts = path_part.split("/", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid resource path: {path_part}")

            category, slug = parts
            content = memory.get_page(category, slug)
            if content is None:
                raise ValueError(f"Page not found: {category}/{slug}")

            return [
                ReadResourceContents(
                    content=content,
                    mime_type="text/markdown",
                )
            ]

    return server


async def run_stdio_server(
    *,
    tools: list[Tool] | None = None,
    memory: WikiMemory | None = None,
) -> None:
    """Run the Birkin MCP server on stdio transport.

    This is the entry point for ``birkin mcp serve``.
    """
    server = create_mcp_server(tools=tools, memory=memory)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
