"""MCP client — manages a single MCP server connection."""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Any, Optional

from mcp.client.session import ClientSession
from mcp.types import CallToolResult, TextContent

from birkin.mcp.transport import open_session
from birkin.mcp.types import MCPServerConfig, MCPToolCallResult, MCPToolInfo

logger = logging.getLogger(__name__)


class MCPClient:
    """Manages a persistent connection to a single MCP server.

    Designed to be used as an async context manager::

        async with MCPClient(config) as client:
            tools = await client.list_tools()
            result = await client.call_tool("echo", {"message": "hi"})
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config
        self._session: Optional[ClientSession] = None
        self._ctx_stack: Optional[Any] = None

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def config(self) -> MCPServerConfig:
        return self._config

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def connect(self) -> None:
        """Open the transport and initialize the MCP session."""
        if self._session is not None:
            logger.warning("MCPClient %r already connected", self.name)
            return

        self._ctx_stack = open_session(self._config)
        self._session = await self._ctx_stack.__aenter__()
        logger.info("MCPClient %r connected", self.name)

    async def disconnect(self) -> None:
        """Close the MCP session and transport."""
        if self._ctx_stack is not None:
            try:
                await self._ctx_stack.__aexit__(None, None, None)
            except (OSError, RuntimeError) as exc:
                logger.warning("Error disconnecting MCP server %r: %s", self.name, exc)
            finally:
                self._session = None
                self._ctx_stack = None
                logger.info("MCPClient %r disconnected", self.name)

    async def __aenter__(self) -> MCPClient:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        await self.disconnect()

    def _ensure_connected(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError(f"MCPClient {self.name!r} is not connected. Call connect() first.")
        return self._session

    async def list_tools(self) -> list[MCPToolInfo]:
        """Discover tools exposed by the MCP server.

        Returns a list of MCPToolInfo (decoupled from the SDK types).
        """
        session = self._ensure_connected()
        result = await session.list_tools()

        tools: list[MCPToolInfo] = []
        for tool in result.tools:
            tools.append(
                MCPToolInfo(
                    server_name=self.name,
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema if tool.inputSchema else {},
                )
            )

        logger.info("MCP server %r exposes %d tools", self.name, len(tools))
        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> MCPToolCallResult:
        """Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool to call.
            arguments: Arguments to pass to the tool.

        Returns:
            MCPToolCallResult with the tool's output.
        """
        session = self._ensure_connected()

        try:
            result: CallToolResult = await session.call_tool(tool_name, arguments)
        except (OSError, RuntimeError, TimeoutError) as exc:
            logger.error("MCP tool call %r on %r failed: %s", tool_name, self.name, exc)
            return MCPToolCallResult(
                content=f"MCP tool call failed: {exc}",
                is_error=True,
            )

        # Extract text content from the result
        text_parts: list[str] = []
        for content_block in result.content:
            if isinstance(content_block, TextContent):
                text_parts.append(content_block.text)
            else:
                text_parts.append(str(content_block))

        return MCPToolCallResult(
            content="\n".join(text_parts) if text_parts else "",
            is_error=result.isError or False,
        )
