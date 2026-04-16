"""Tests for tool interfaces, registry, and loader."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec
from birkin.tools.builtins.shell import _is_allowed, _is_blocked
from birkin.tools.loader import load_tools
from birkin.tools.registry import ToolRegistry


class DummyTool(Tool):
    """Concrete tool for testing."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="dummy",
            description="A test tool",
            parameters=[
                ToolParameter(name="input", type="string", description="Input text"),
            ],
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        return ToolOutput(
            success=True,
            output=f"echo: {args.get('input', '')}",
        )


class TestToolSpec:
    def test_to_provider_schema(self):
        tool = DummyTool()
        schema = tool.to_provider_schema()
        assert schema["name"] == "dummy"
        assert "input" in schema["parameters"]["properties"]
        assert "input" in schema["parameters"]["required"]


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = DummyTool()
        reg.register(tool)
        assert reg.get("dummy") is tool

    def test_duplicate_raises(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(DummyTool())

    def test_unregister(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        reg.unregister("dummy")
        assert reg.get("dummy") is None

    def test_list_all(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        assert len(reg.list_all()) == 1

    def test_export_schemas(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        schemas = reg.export_schemas()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "dummy"

    def test_len(self):
        reg = ToolRegistry()
        assert len(reg) == 0
        reg.register(DummyTool())
        assert len(reg) == 1


class TestLoadTools:
    def test_loads_builtin_tools(self):
        from birkin.tools.registry import reset_registry

        reset_registry()
        tools = load_tools()
        names = {t.spec.name for t in tools}
        assert "shell" in names
        assert "web_search" in names
        assert "file_read" in names
        assert "file_write" in names
        reset_registry()


class TestShellAllowlist:
    """Tests for the allowlist + metacharacter rejection in the shell tool."""

    def test_allowed_command_ls(self):
        allowed, reason = _is_allowed("ls -la")
        assert allowed is True
        assert reason is None

    def test_denied_rm_not_in_allowlist(self):
        allowed, reason = _is_allowed("rm -rf /")
        assert allowed is False
        assert "rm" in reason

    def test_denied_bash_not_in_allowlist(self):
        allowed, reason = _is_allowed('bash -c "ls"')
        assert allowed is False
        assert "bash" in reason

    def test_denied_pipe_metachar(self):
        allowed, reason = _is_allowed("ls | grep foo")
        assert allowed is False
        assert "metacharacter" in reason.lower()

    def test_denied_subshell(self):
        allowed, reason = _is_allowed("ls $(whoami)")
        assert allowed is False
        assert "metacharacter" in reason.lower()

    def test_denied_chain(self):
        allowed, reason = _is_allowed("ls && echo done")
        assert allowed is False
        assert "metacharacter" in reason.lower()

    def test_env_var_extends_allowlist(self):
        with patch.dict("os.environ", {"BIRKIN_SHELL_ALLOWLIST": "curl"}):
            allowed, reason = _is_allowed("curl https://example.com")
            assert allowed is True
            assert reason is None

    def test_sandbox_off_bypasses_allowlist(self):
        with patch.dict("os.environ", {"BIRKIN_SHELL_SANDBOX": "off"}):
            allowed, reason = _is_allowed("rm -rf /")
            assert allowed is True
            assert reason is None

    def test_legacy_blocklist_still_active(self):
        """_is_blocked remains functional as defense-in-depth."""
        reason = _is_blocked("rm -rf /")
        assert reason is not None
        assert "Blocked" in reason
