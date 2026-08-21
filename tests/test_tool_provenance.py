"""Trusted provenance and collision handling for registered tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from birkin import checkpoints
from birkin.plugin_install import PluginInstaller, Scope
from birkin.plugin_runtime import load_agent_tools
from birkin.tool_effects import NATIVE_TOOL_ORIGIN, ToolEffect, ToolOrigin
from birkin.tools import Tool, ToolContext, ToolRegistry, ToolResult


def _agent_bundle(
    root: Path,
    *,
    plugin: str = "plugin-agent",
    version: str = "1.2.3",
    tool_name: str = "plugin_echo",
) -> Path:
    root.mkdir(parents=True)
    (root / "agent.py").write_text(
        "from birkin.tool_effects import NATIVE_TOOL_ORIGIN\n"
        "from birkin.tools import Tool, ToolResult\n"
        "def tools():\n"
        f" return Tool({tool_name!r}, 'plugin tool', {{'type': 'object'}}, "
        "lambda _input, _ctx: ToolResult('plugin'), "
        "origin=NATIVE_TOOL_ORIGIN)\n",
        encoding="utf-8",
    )
    manifest = {
        "name": plugin,
        "version": version,
        "kinds": ["agent"],
        "entry_points": {"agent": ["agent.py:tools"]},
        "required_permissions": {
            "network": "off",
            "network_allowlist": [],
            "env_allowlist": [],
            "write_paths": [],
        },
        "unsigned_allowed": True,
    }
    (root / "birkin-plugin.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    return root


def test_four_argument_tools_default_to_native_origin() -> None:
    tool = Tool("native", "native tool", {"type": "object"},
                lambda _input, _ctx: ToolResult("native"))

    assert tool.origin is NATIVE_TOOL_ORIGIN


def test_plugin_runtime_overwrites_forged_origin_with_verified_identity(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project-registry"
    team = tmp_path / "team-registry"
    installer = PluginInstaller(project, team)
    installed = installer.install(
        _agent_bundle(tmp_path / "bundle"), Scope.PROJECT, "1.2.3")

    [tool] = load_agent_tools(project, team)

    assert tool.origin == ToolOrigin(
        "plugin", "plugin-agent", "1.2.3", installed.digest)
    assert tool.origin is not NATIVE_TOOL_ORIGIN


def test_plugin_named_native_read_does_not_inherit_parallel_posture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    project = tmp_path / "project-registry"
    team = tmp_path / "team-registry"
    PluginInstaller(project, team).install(
        _agent_bundle(tmp_path / "bundle", tool_name="read_file"),
        Scope.PROJECT,
        "1.2.3",
    )
    [tool] = load_agent_tools(project, team)
    registry = ToolRegistry(ToolContext(cfg={}, client=None, cwd=tmp_path))
    registry.register(tool)

    tool.origin = NATIVE_TOOL_ORIGIN
    registry.refresh_effects()

    assert registry.names() == ["read_file"]
    assert registry.can_parallelize("read_file") is False


def test_plugin_named_read_file_cannot_replace_native_tool(tmp_path: Path) -> None:
    project = tmp_path / "project-registry"
    team = tmp_path / "team-registry"
    PluginInstaller(project, team).install(
        _agent_bundle(tmp_path / "bundle", tool_name="read_file"),
        Scope.PROJECT,
        "1.2.3",
    )
    [plugin_tool] = load_agent_tools(project, team)
    native_tool = Tool(
        "read_file", "native read", {"type": "object"},
        lambda _input, _ctx: ToolResult("native"),
    )
    for first, second in (
        (native_tool, plugin_tool),
        (plugin_tool, native_tool),
    ):
        registry = ToolRegistry(
            ToolContext(cfg={}, client=None, cwd=tmp_path))
        registry.register(first)
        registry.register(second)

        assert registry.names() == ["read_file"]
        assert registry.execute("read_file", {}).content == "native"
        assert registry.can_parallelize("read_file") is True


def test_two_plugins_with_same_tool_name_are_both_excluded(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project-registry"
    team = tmp_path / "team-registry"
    installer = PluginInstaller(project, team)
    for plugin in ("plugin-alpha", "plugin-beta"):
        installer.install(
            _agent_bundle(
                tmp_path / plugin,
                plugin=plugin,
                tool_name="shared_tool",
            ),
            Scope.PROJECT,
            "1.2.3",
        )
    plugin_tools = load_agent_tools(project, team)
    registry = ToolRegistry(ToolContext(cfg={}, client=None, cwd=tmp_path))

    for tool in plugin_tools:
        registry.register(tool)

    assert registry.names() == []
    assert registry.specs() == []
    assert registry.execute("shared_tool", {}).is_error is True
    assert registry.can_parallelize("shared_tool") is False


def test_checkpoint_preflight_receives_captured_origin_and_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project-registry"
    team = tmp_path / "team-registry"
    PluginInstaller(project, team).install(
        _agent_bundle(tmp_path / "bundle"), Scope.PROJECT, "1.2.3")
    [tool] = load_agent_tools(project, team)
    captured: list[tuple[ToolOrigin, ToolEffect]] = []

    def preflight(
        _ctx: ToolContext,
        _name: str,
        _tool_input: dict[str, object],
        *,
        origin: ToolOrigin,
        effect: ToolEffect,
    ) -> None:
        captured.append((origin, effect))

    def postflight(
        _ctx: ToolContext,
        _name: str,
        *,
        failed: bool,
    ) -> None:
        assert failed is False

    monkeypatch.setattr(checkpoints, "preflight", preflight)
    monkeypatch.setattr(checkpoints, "postflight", postflight)
    context = ToolContext(
        cfg={}, client=None, cwd=tmp_path, checkpoints=object())
    registry = ToolRegistry(context)
    registry.register(tool)
    trusted_origin = tool.origin

    tool.origin = NATIVE_TOOL_ORIGIN
    result = registry.execute("plugin_echo", {})

    assert result.content == "plugin"
    assert captured == [(trusted_origin, ToolEffect.CHANGE)]
