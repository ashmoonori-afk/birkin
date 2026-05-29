"""Unit tests for MCP server listing/parsing (no real `claude` call)."""

from __future__ import annotations

import subprocess

from birkin import mcp

_SAMPLE = """Checking MCP server health…

claude.ai Google Drive: https://drivemcp.googleapis.com/mcp/v1 - ! Needs authentication
claude.ai Notion: https://mcp.notion.com/mcp - ✓ Connected
plugin:github:github: https://api.githubcopilot.com/mcp/ (HTTP) - ✗ Failed to connect
plugin:playwright:playwright: npx @playwright/mcp@latest - ✓ Connected
pencil: C:\\Users\\lg\\.pencil\\mcp\\server.exe --app antigravity - ✓ Connected
"""


def test_parse_list_names_and_status():
    servers = mcp._parse_list(_SAMPLE)
    by_name = {s.name: s for s in servers}
    assert "claude.ai Notion" in by_name
    assert "plugin:playwright:playwright" in by_name      # colons in name preserved
    assert "pencil" in by_name
    assert by_name["claude.ai Notion"].connected is True
    assert by_name["plugin:github:github"].connected is False
    assert by_name["claude.ai Google Drive"].connected is False


def test_parse_list_extracts_detail():
    by_name = {s.name: s for s in mcp._parse_list(_SAMPLE)}
    assert by_name["claude.ai Notion"].detail == "https://mcp.notion.com/mcp"
    assert by_name["plugin:playwright:playwright"].detail == "npx @playwright/mcp@latest"


def test_parse_list_skips_header_and_blanks():
    servers = mcp._parse_list(_SAMPLE)
    assert all("Checking MCP" not in s.name for s in servers)
    assert len(servers) == 5


def test_list_servers_handles_missing_claude(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError()
    monkeypatch.setattr(mcp, "run", boom)
    servers, err = mcp.list_servers()
    assert servers == [] and err and "claude" in err


def test_list_servers_parses_capture(monkeypatch):
    def fake_run(args, *, capture=False, timeout=60):
        return subprocess.CompletedProcess(args, 0, stdout=_SAMPLE, stderr="")
    monkeypatch.setattr(mcp, "run", fake_run)
    servers, err = mcp.list_servers()
    assert err is None
    assert {"pencil", "claude.ai Notion"} <= {s.name for s in servers}
