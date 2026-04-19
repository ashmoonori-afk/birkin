"""MCP transport layer — thin wrappers around the mcp SDK transports."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

from birkin.mcp.types import MCPServerConfig, TransportType

logger = logging.getLogger(__name__)


@asynccontextmanager
async def open_session(config: MCPServerConfig) -> AsyncGenerator[ClientSession, None]:
    """Open an MCP ClientSession for the given server config.

    Dispatches to the correct transport (stdio or SSE) based on
    ``config.transport`` and yields an initialized ``ClientSession``.

    Usage::

        async with open_session(server_config) as session:
            tools = await session.list_tools()
    """
    if config.transport == TransportType.STDIO:
        async with _open_stdio(config) as session:
            yield session
    elif config.transport == TransportType.SSE:
        async with _open_sse(config) as session:
            yield session
    else:
        raise ValueError(f"Unsupported transport: {config.transport}")


@asynccontextmanager
async def _open_stdio(config: MCPServerConfig) -> AsyncGenerator[ClientSession, None]:
    """Open a stdio-based MCP session."""
    if not config.command:
        raise ValueError(f"MCP server {config.name!r} uses stdio transport but has no 'command'")

    env: dict[str, str] | None = config.env if config.env else None

    params = StdioServerParameters(
        command=config.command,
        args=config.args,
        env=env,
        cwd=config.cwd,
    )

    logger.info("Connecting to MCP server %r via stdio: %s %s", config.name, config.command, config.args)

    async with stdio_client(params) as (read_stream, write_stream), ClientSession(read_stream, write_stream) as session:
        await session.initialize()
        logger.info("MCP server %r initialized (stdio)", config.name)
        yield session


@asynccontextmanager
async def _open_sse(config: MCPServerConfig) -> AsyncGenerator[ClientSession, None]:
    """Open an SSE-based MCP session."""
    if not config.url:
        raise ValueError(f"MCP server {config.name!r} uses SSE transport but has no 'url'")

    logger.info("Connecting to MCP server %r via SSE: %s", config.name, config.url)

    async with (
        sse_client(config.url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        logger.info("MCP server %r initialized (SSE)", config.name)
        yield session
