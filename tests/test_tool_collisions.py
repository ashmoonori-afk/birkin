"""Collision rules for native and plugin tool registrations."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin.memory import VaultMemory
from birkin.skills.manager import SkillManager
from birkin.tool_effects import ToolOrigin
from birkin.tool_inventory import NATIVE_TOOL_NAMES
from birkin.tools import (
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    build_tool_groups,
)


def _registry(tmp_path: Path) -> ToolRegistry:
    return ToolRegistry(ToolContext(cfg={}, client=None, cwd=tmp_path))


def _tool(name: str, result: str, *, origin: ToolOrigin) -> Tool:
    return Tool(
        name,
        f"{result} tool",
        {"type": "object"},
        lambda _input, _ctx: ToolResult(result),
        origin=origin,
    )


def test_native_inventory_matches_every_runtime_group_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    companion = home / "companion" / "state.json"
    companion.parent.mkdir(parents=True)
    _ = companion.write_text("{}", encoding="utf-8")
    cfg = {
        "desktop_tools": True,
        "computer_use": {"enabled": True},
        "profile": {"enabled": True},
    }
    memory = VaultMemory(cfg)
    context = ToolContext(
        cfg=cfg,
        client=None,
        cwd=tmp_path,
        skills=SkillManager([]),
        memory=memory,
    )

    runtime_names = {
        tool.name
        for tools in build_tool_groups(context).values()
        for tool in tools
        if tool.origin.kind == "native"
    }

    assert runtime_names == NATIVE_TOOL_NAMES


@pytest.mark.parametrize("native_first", [True, False])
def test_plugin_named_read_file_does_not_replace_native_handler(
    tmp_path: Path,
    native_first: bool,
) -> None:
    registry = _registry(tmp_path)
    native = Tool(
        "read_file",
        "native read",
        {"type": "object"},
        lambda _input, _ctx: ToolResult("native"),
    )
    plugin = _tool(
        "read_file",
        "plugin",
        origin=ToolOrigin("plugin", "reader", "1.0.0", "a" * 64),
    )

    for tool in (native, plugin) if native_first else (plugin, native):
        registry.register(tool)

    assert registry.names() == ["read_file"]
    assert registry.execute("read_file", {}).content == "native"


def test_plugins_with_the_same_name_are_both_excluded(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.register(
        _tool(
            "shared",
            "first",
            origin=ToolOrigin("plugin", "first-plugin", "1.0.0", "a" * 64),
        )
    )
    registry.register(
        _tool(
            "shared",
            "second",
            origin=ToolOrigin("plugin", "second-plugin", "2.0.0", "b" * 64),
        )
    )

    assert "shared" not in registry.names()
    assert all(spec["name"] != "shared" for spec in registry.specs())
    result = registry.execute("shared", {})
    assert result.is_error is True


def test_plugin_collision_remains_excluded_after_later_registration(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    for plugin, digest in (("first", "a"), ("second", "b"), ("third", "c")):
        registry.register(
            _tool(
                "shared",
                plugin,
                origin=ToolOrigin("plugin", plugin, "1.0.0", digest * 64),
            )
        )

    assert "shared" not in registry.names()
    assert all(spec["name"] != "shared" for spec in registry.specs())
    assert registry.execute("shared", {}).is_error is True


def test_registering_same_native_name_twice_raises(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.register(
        Tool(
            "read_file",
            "first native",
            {"type": "object"},
            lambda _input, _ctx: ToolResult("first"),
        )
    )

    with pytest.raises(ValueError):
        registry.register(
            Tool(
                "read_file",
                "second native",
                {"type": "object"},
                lambda _input, _ctx: ToolResult("second"),
            )
        )


def test_non_colliding_plugin_registers_and_executes(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.register(
        _tool(
            "plugin_echo",
            "plugin result",
            origin=ToolOrigin("plugin", "echo", "1.0.0", "d" * 64),
        )
    )

    assert registry.names() == ["plugin_echo"]
    assert [spec["name"] for spec in registry.specs()] == ["plugin_echo"]
    result = registry.execute("plugin_echo", {})
    assert result.is_error is False
    assert result.content == "plugin result"
