"""MCP registry — manages multiple MCP server connections."""

from __future__ import annotations

import logging
from typing import Optional

from birkin.mcp.client import MCPClient
from birkin.mcp.types import MCPServerConfig, MCPToolInfo

logger = logging.getLogger(__name__)


class MCPRegistry:
    """Discover, connect, and manage multiple MCP servers.

    Usage::

        registry = MCPRegistry()
        await registry.add_server(config)
        tools = await registry.list_all_tools()
        result = await registry.call_tool("server/tool_name", {...})
        await registry.shutdown()
    """

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._tools: dict[str, MCPToolInfo] = {}  # keyed by "server/tool_name"

    @property
    def server_names(self) -> list[str]:
        """Return names of all registered servers."""
        return list(self._clients.keys())

    def get_client(self, server_name: str) -> Optional[MCPClient]:
        """Look up a connected client by server name."""
        return self._clients.get(server_name)

    async def add_server(self, config: MCPServerConfig) -> list[MCPToolInfo]:
        """Connect to an MCP server and discover its tools.

        Args:
            config: Server configuration.

        Returns:
            List of tools discovered from this server.

        Raises:
            ValueError: If a server with this name is already registered.
        """
        if config.name in self._clients:
            raise ValueError(f"MCP server already registered: {config.name!r}")

        client = MCPClient(config)
        try:
            await client.connect()
        except (OSError, RuntimeError, TimeoutError) as exc:
            logger.error("Failed to connect to MCP server %r: %s", config.name, exc)
            raise

        self._clients[config.name] = client

        # Discover tools
        tools = await client.list_tools()
        for tool in tools:
            qualified_name = f"{config.name}/{tool.name}"
            self._tools[qualified_name] = tool

        logger.info(
            "MCP server %r added with %d tools: %s",
            config.name,
            len(tools),
            [t.name for t in tools],
        )
        return tools

    async def remove_server(self, server_name: str) -> None:
        """Disconnect and remove an MCP server."""
        client = self._clients.pop(server_name, None)
        if client is None:
            return

        # Remove tools belonging to this server
        to_remove = [k for k, v in self._tools.items() if v.server_name == server_name]
        for key in to_remove:
            del self._tools[key]

        await client.disconnect()
        logger.info("MCP server %r removed", server_name)

    def list_all_tools(self) -> list[MCPToolInfo]:
        """Return all tools from all connected servers."""
        return list(self._tools.values())

    def get_tool(self, qualified_name: str) -> Optional[MCPToolInfo]:
        """Look up a tool by qualified name ('server/tool_name')."""
        return self._tools.get(qualified_name)

    def find_tool(self, tool_name: str) -> Optional[MCPToolInfo]:
        """Find a tool by unqualified name (first match wins).

        When tool names are unique across servers, this is convenient.
        For ambiguous names, use the qualified 'server/tool_name' form.
        """
        for info in self._tools.values():
            if info.name == tool_name:
                return info
        return None

    async def load_from_configs(self, configs: list[MCPServerConfig]) -> list[MCPToolInfo]:
        """Connect to multiple servers from a list of configs.

        Skips disabled servers and servers that fail to connect.
        Returns all successfully discovered tools.
        """
        all_tools: list[MCPToolInfo] = []

        for config in configs:
            if not config.enabled:
                logger.info("Skipping disabled MCP server: %r", config.name)
                continue
            try:
                tools = await self.add_server(config)
                all_tools.extend(tools)
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                logger.error("Skipping MCP server %r: %s", config.name, exc)

        return all_tools

    async def shutdown(self) -> None:
        """Disconnect all MCP servers."""
        names = list(self._clients.keys())
        for name in names:
            await self.remove_server(name)
        logger.info("MCPRegistry shutdown complete")

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"MCPRegistry({len(self._clients)} servers, {len(self._tools)} tools)"
