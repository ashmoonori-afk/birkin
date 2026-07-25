"""Drive the MCP server as a real subprocess, over real stdio.

This is the surface a Claude Code user installs to get birkin's vault, so
"it imports" is not the bar: the process must complete an MCP handshake,
advertise its tools, and write a note that is then findable by search — the
same round trip any MCP host performs.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest


def _rpc(proc, msg: dict) -> dict | None:
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if "id" not in msg:
        return None
    line = proc.stdout.readline()
    assert line, "server closed stdout"
    return json.loads(line)


@pytest.fixture
def server(tmp_path, monkeypatch):
    import os
    env = dict(os.environ, BIRKIN_HOME=str(tmp_path), PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "birkin", "mcp-serve"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", env=env, bufsize=1)
    try:
        yield proc
    finally:
        try:
            proc.stdin.close()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def test_handshake_advertises_the_vault_tools(server):
    res = _rpc(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05"}})
    assert res["result"]["serverInfo"]["name"] == "birkin"
    assert "tools" in res["result"]["capabilities"]

    _rpc(server, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    res = _rpc(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in res["result"]["tools"]}
    assert {"memory_search", "memory_write_note", "memory_get_note",
            "load_skill"} <= names
    for tool in res["result"]["tools"]:
        assert tool["description"] and tool["inputSchema"]["type"] == "object"


def test_a_note_written_over_mcp_is_findable_over_mcp(server):
    _rpc(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05"}})
    res = _rpc(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "memory_write_note", "arguments": {
                            "title": "배포 파이프라인",
                            "body": "스테이징 먼저, 그다음 프로덕션",
                            "sources": ["mcp-e2e"]}}})
    assert res["result"]["isError"] is False, res["result"]

    res = _rpc(server, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "memory_search",
                                   "arguments": {"query": "배포"}}})
    text = res["result"]["content"][0]["text"]
    assert res["result"]["isError"] is False
    assert "배포" in text


def test_shell_is_never_exposed(server):
    """Only safe, reversible tools cross this boundary."""
    _rpc(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05"}})
    res = _rpc(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in res["result"]["tools"]}
    assert not {n for n in names if "shell" in n or "bash" in n}


def test_bad_input_never_kills_the_server(server):
    _rpc(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05"}})
    server.stdin.write("{not json\n")
    server.stdin.flush()
    assert json.loads(server.stdout.readline())["error"]["code"] == -32700

    res = _rpc(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "no_such_tool", "arguments": {}}})
    assert res["result"]["isError"] is True

    res = _rpc(server, {"jsonrpc": "2.0", "id": 3, "method": "nonsense"})
    assert res["error"]["code"] == -32601

    res = _rpc(server, {"jsonrpc": "2.0", "id": 4, "method": "ping"})
    assert res["result"] == {}          # still alive after all of that
