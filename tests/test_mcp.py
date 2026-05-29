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


def test_run_builds_claude_mcp_argv(monkeypatch):
    captured = {}

    def fake_run(argv, **kw):
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(mcp.subprocess, "run", fake_run)
    mcp.run(["list"])
    argv = captured["argv"]
    assert "claude" in argv and "mcp" in argv and "list" in argv


def test_run_capture_returns_completed(monkeypatch):
    monkeypatch.setattr(mcp.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 0,
                                                                       stdout="x", stderr=""))
    cp = mcp.run(["list"], capture=True)
    assert cp.returncode == 0 and cp.stdout == "x"


def test_list_servers_error_on_nonzero_empty(monkeypatch):
    monkeypatch.setattr(mcp, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 2, stdout="", stderr=""))
    servers, err = mcp.list_servers()
    assert servers == [] and err and "failed" in err


def test_list_servers_timeout(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=60)
    monkeypatch.setattr(mcp, "run", boom)
    servers, err = mcp.list_servers()
    assert servers == [] and err and "timed out" in err


# -- `birkin mcp` CLI command ----------------------------------------------

def _ns(args):
    import types
    return types.SimpleNamespace(args=args)


def test_cmd_mcp_list(monkeypatch, capsys):
    from birkin import cli
    monkeypatch.setattr(mcp, "list_servers",
                        lambda **k: ([mcp.McpServer("n", "d", "✓ Connected", True)], None))
    assert cli._cmd_mcp(_ns([])) == 0
    assert "MCP servers" in capsys.readouterr().out


def test_cmd_mcp_list_empty(monkeypatch):
    from birkin import cli
    monkeypatch.setattr(mcp, "list_servers", lambda **k: ([], None))
    assert cli._cmd_mcp(_ns([])) == 0


def test_cmd_mcp_list_error(monkeypatch):
    from birkin import cli
    monkeypatch.setattr(mcp, "list_servers", lambda **k: ([], "no claude on PATH"))
    assert cli._cmd_mcp(_ns([])) == 1


def test_cmd_mcp_passthrough(monkeypatch):
    from birkin import cli
    monkeypatch.setattr(mcp, "run",
                        lambda sub: subprocess.CompletedProcess(sub, 0))
    assert cli._cmd_mcp(_ns(["list"])) == 0
