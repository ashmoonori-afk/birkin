"""MCP tool adapter — wraps an MCP tool as a Birkin Tool."""

from __future__ import annotations

from typing import Any

from birkin.mcp.client import MCPClient
from birkin.mcp.types import MCPToolInfo
from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec


def _json_schema_to_params(input_schema: dict[str, Any]) -> list[ToolParameter]:
    """Convert a JSON Schema 'properties' dict to a list of ToolParameter."""
    properties = input_schema.get("properties", {})
    required_set = set(input_schema.get("required", []))
    params: list[ToolParameter] = []

    for name, prop in properties.items():
        params.append(
            ToolParameter(
                name=name,
                type=prop.get("type", "string"),
                description=prop.get("description", ""),
                required=name in required_set,
                default=prop.get("default"),
                enum=prop.get("enum"),
            )
        )

    return params


class MCPToolAdapter(Tool):
    """Adapts an MCP tool to the Birkin Tool ABC.

    This allows MCP tools to be used transparently alongside built-in
    tools in the Agent's tool registry.

    The tool name is prefixed with the server name to avoid collisions:
    ``mcp__{server}__{tool}`` (e.g. ``mcp__filesystem__read_file``).
    """

    def __init__(self, tool_info: MCPToolInfo, client: MCPClient) -> None:
        self._info = tool_info
        self._client = client
        self._qualified_name = f"mcp__{tool_info.server_name}__{tool_info.name}"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self._qualified_name,
            description=f"[MCP:{self._info.server_name}] {self._info.description}",
            parameters=_json_schema_to_params(self._info.input_schema),
            toolset="mcp",
        )

    @property
    def server_name(self) -> str:
        return self._info.server_name

    @property
    def mcp_tool_name(self) -> str:
        """The original tool name on the MCP server (without prefix)."""
        return self._info.name

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        """Call the MCP tool via the client and return a ToolOutput."""
        if not self._client.connected:
            return ToolOutput(
                success=False,
                output="",
                error=f"MCP server {self.server_name!r} is not connected",
            )

        result = await self._client.call_tool(self._info.name, args)

        return ToolOutput(
            success=not result.is_error,
            output=result.content if not result.is_error else "",
            error=result.content if result.is_error else None,
            metadata=result.metadata,
        )

    def check_available(self) -> bool:
        return self._client.connected

    def to_provider_schema(self) -> dict[str, Any]:
        """Export using the original MCP input schema for full fidelity.

        The base class builds a schema from ToolParameter, which works
        but loses nested object types. Using the original inputSchema
        preserves the full JSON Schema that the MCP server declared.
        """
        return {
            "name": self._qualified_name,
            "description": f"[MCP:{self._info.server_name}] {self._info.description}",
            "parameters": self._info.input_schema if self._info.input_schema else {
                "type": "object",
                "properties": {},
            },
        }
