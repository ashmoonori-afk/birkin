"""MCP type definitions for Birkin."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class TransportType(str, Enum):
    """Supported MCP transport types."""

    STDIO = "stdio"
    SSE = "sse"


class MCPServerConfig(BaseModel, frozen=True):
    """Configuration for a single MCP server.

    Matches the standard MCP server config format used by Claude Code,
    Cursor, etc. for maximum interoperability.

    Example in birkin_config.json::

        {
            "mcp_servers": [
                {
                    "name": "filesystem",
                    "transport": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    "env": {}
                },
                {
                    "name": "remote-tools",
                    "transport": "sse",
                    "url": "http://localhost:8080/sse"
                }
            ]
        }
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    transport: TransportType = TransportType.STDIO
    # stdio fields
    command: Optional[str] = None
    args: list[str] = []
    env: dict[str, str] = {}
    cwd: Optional[str] = None
    # sse fields
    url: Optional[str] = None
    # common
    enabled: bool = True


@dataclass(frozen=True)
class MCPToolInfo:
    """Lightweight snapshot of a tool discovered from an MCP server.

    Decoupled from the mcp SDK's ``Tool`` model so the rest of Birkin
    does not depend on the SDK types directly.
    """

    server_name: str
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class MCPToolCallResult:
    """Result of calling a tool on an MCP server."""

    content: str
    is_error: bool = False
    metadata: Optional[dict[str, Any]] = None
