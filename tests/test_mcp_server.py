"""Unit tests for the birkin MCP server (JSON-RPC handling + tool wiring)."""

from __future__ import annotations

import json

from birkin import mcp_server


def _fake_tools():
    calls = {}

    def handler(args):
        calls["args"] = args
        return "ok-result", False

    return {"memory_search": {"description": "d", "schema": {"type": "object"},
                              "handler": handler}}, calls


def test_initialize_echoes_protocol_and_serverinfo():
    out = json.loads(mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05"}}, {}))
    assert out["id"] == 1
    assert out["result"]["protocolVersion"] == "2024-11-05"
    assert out["result"]["serverInfo"]["name"] == "birkin"
    assert "tools" in out["result"]["capabilities"]


def test_initialized_notification_returns_none():
    assert mcp_server.handle_message(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}, {}) is None


def test_ping():
    out = json.loads(mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 5, "method": "ping"}, {}))
    assert out["result"] == {} and out["id"] == 5


def test_tools_list_shape():
    tools, _ = _fake_tools()
    out = json.loads(mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, tools))
    names = [t["name"] for t in out["result"]["tools"]]
    assert names == ["memory_search"]
    assert out["result"]["tools"][0]["inputSchema"] == {"type": "object"}


def test_tools_call_runs_handler():
    tools, calls = _fake_tools()
    out = json.loads(mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "memory_search", "arguments": {"query": "x"}}}, tools))
    assert calls["args"] == {"query": "x"}
    assert out["result"]["isError"] is False
    assert out["result"]["content"][0]["text"] == "ok-result"


def test_tools_call_unknown_tool_is_error():
    out = json.loads(mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "nope", "arguments": {}}}, {}))
    assert out["result"]["isError"] is True


def test_tools_call_handler_exception_is_caught():
    def boom(args):
        raise RuntimeError("kaboom")
    tools = {"t": {"description": "d", "schema": {}, "handler": boom}}
    out = json.loads(mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
         "params": {"name": "t", "arguments": {}}}, tools))
    assert out["result"]["isError"] is True
    assert "kaboom" in out["result"]["content"][0]["text"]


def test_unknown_method_returns_error():
    out = json.loads(mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 9, "method": "frobnicate"}, {}))
    assert out["error"]["code"] == -32601


def test_build_tools_exposes_safe_set(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    tools = mcp_server._build_tools()
    names = set(tools)
    assert {"memory_write_note", "memory_search", "create_skill",
            "propose_action"} <= names
    # never expose shell / arbitrary execution
    assert not any("shell" in n or "bash" in n.lower() for n in names)


def test_config_helpers(tmp_path):
    cfg = mcp_server.mcp_config_dict()
    assert "birkin" in cfg["mcpServers"]
    assert cfg["mcpServers"]["birkin"]["args"] == ["-m", "birkin", "mcp-serve"]
    p = mcp_server.write_mcp_config(tmp_path / "m.json")
    assert json.loads(p.read_text())["mcpServers"]["birkin"]
    assert mcp_server.birkin_tool_patterns() == ["mcp__birkin__*"]
