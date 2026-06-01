"""Per-skill scoped permissions / MCP (v2 #8) — frontmatter accessor + check."""

from __future__ import annotations

from pathlib import Path

from birkin.skills.loader import Skill


def _skill(meta: dict) -> Skill:
    return Skill(name="s", description="", path=Path("SKILL.md"),
                 source="bundled", meta=meta)


def test_permissions_list_is_allow_list():
    s = _skill({"permissions": ["read_file", "write_file"], "mcp": ["notion"]})
    p = s.permissions
    assert p["allow"] == ["read_file", "write_file"] and p["mcp"] == ["notion"]
    assert s.tool_allowed("read_file") is True
    assert s.tool_allowed("run_shell") is False        # not in allow-list


def test_permissions_dict_allow_deny():
    s = _skill({"permissions": {"allow": ["read_file"], "deny": ["run_shell"]}})
    assert s.tool_allowed("read_file") is True
    assert s.tool_allowed("run_shell") is False


def test_permissions_under_metadata_birkin():
    s = _skill({"metadata": {"birkin": {"permissions": {"deny": ["run_shell"]}}}})
    # empty allow -> everything allowed except denied
    assert s.tool_allowed("read_file") is True
    assert s.tool_allowed("run_shell") is False


def test_no_permissions_means_unrestricted():
    s = _skill({"name": "s"})
    assert s.permissions == {"allow": [], "deny": [], "mcp": []}
    assert s.tool_allowed("anything") is True
