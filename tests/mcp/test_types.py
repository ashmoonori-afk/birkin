"""Tests for birkin.mcp.types."""

import pytest
from pydantic import ValidationError

from birkin.mcp.types import (
    MCPServerConfig,
    MCPToolCallResult,
    MCPToolInfo,
    TransportType,
)


class TestMCPServerConfig:
    def test_stdio_defaults(self) -> None:
        cfg = MCPServerConfig(name="test", command="echo")
        assert cfg.transport == TransportType.STDIO
        assert cfg.args == []
        assert cfg.env == {}
        assert cfg.enabled is True
        assert cfg.url is None

    def test_sse_config(self) -> None:
        cfg = MCPServerConfig(
            name="remote",
            transport="sse",
            url="http://localhost:8080/sse",
        )
        assert cfg.transport == TransportType.SSE
        assert cfg.url == "http://localhost:8080/sse"
        assert cfg.command is None

    def test_disabled_server(self) -> None:
        cfg = MCPServerConfig(name="off", command="noop", enabled=False)
        assert cfg.enabled is False

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MCPServerConfig(name="bad", command="echo", unknown_field="x")

    def test_frozen(self) -> None:
        cfg = MCPServerConfig(name="frozen", command="echo")
        with pytest.raises(ValidationError):
            cfg.name = "changed"


class TestMCPToolInfo:
    def test_creation(self) -> None:
        info = MCPToolInfo(
            server_name="fs",
            name="read_file",
            description="Read a file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )
        assert info.server_name == "fs"
        assert info.name == "read_file"
        assert "path" in info.input_schema["properties"]

    def test_frozen(self) -> None:
        info = MCPToolInfo(server_name="s", name="t", description="d", input_schema={})
        with pytest.raises(AttributeError):
            info.name = "changed"


class TestMCPToolCallResult:
    def test_success(self) -> None:
        result = MCPToolCallResult(content="hello")
        assert result.is_error is False
        assert result.content == "hello"

    def test_error(self) -> None:
        result = MCPToolCallResult(content="fail", is_error=True)
        assert result.is_error is True
