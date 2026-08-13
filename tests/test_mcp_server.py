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
            "propose_action", "skills_list", "load_skill"} <= names
    # never expose shell / arbitrary execution
    assert not any("shell" in n or "bash" in n.lower() for n in names)


def test_build_tools_memory_scope_excludes_non_memory_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setenv("BIRKIN_MCP_SCOPE", "memory")

    names = set(mcp_server._build_tools())

    assert {"remember", "memory_write_note", "memory_search"} <= names
    assert not {"create_skill", "load_skill", "propose_action"} & names


def test_serve_roundtrip_and_parse_error(monkeypatch):
    """serve() loop: real request/response framing + a -32700 on bad JSON."""
    import io
    monkeypatch.setattr(mcp_server, "_build_tools", lambda: {})
    inp = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {}}) + "\n"
        + "{ not valid json\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}) + "\n")
    out = io.StringIO()
    assert mcp_server.serve(stdin=inp, stdout=out) == 0
    lines = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    assert lines[0]["id"] == 1 and "result" in lines[0]
    assert any(line.get("error", {}).get("code") == -32700 for line in lines)
    assert lines[-1]["id"] == 2 and lines[-1]["result"] == {}


def test_serve_bounds_frame_read_before_allocation(monkeypatch):
    import io

    class _Input:
        def __init__(self) -> None:
            self.data = "x" * 33 + "\n"
            self.offset = 0
            self.iterated = False
            self.read_sizes: list[int] = []

        def __iter__(self):
            self.iterated = True
            yield self.data

        def readline(self, size: int = -1) -> str:
            self.read_sizes.append(size)
            if self.offset >= len(self.data):
                return ""
            end = len(self.data)
            if size >= 0:
                end = min(end, self.offset + size)
            chunk = self.data[self.offset:end]
            self.offset = end
            return chunk

    source = _Input()
    stdout = io.StringIO()
    monkeypatch.setattr(mcp_server, "_MAX_LINE_BYTES", 32)
    monkeypatch.setattr(mcp_server, "_build_tools", lambda: {})

    assert mcp_server.serve(stdin=source, stdout=stdout) == 0

    assert not source.iterated
    assert source.read_sizes
    assert all(0 < size <= 33 for size in source.read_sizes)
    assert "request too large" in stdout.getvalue()
    assert "parse error" not in stdout.getvalue()


def test_create_skill_handler_success_and_error(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    tools = mcp_server._build_tools()
    text, err = tools["create_skill"]["handler"](
        {"name": "my-skill", "description": "d", "body": "# B\nbody"})
    assert err is False and "Created" in text
    text, err = tools["create_skill"]["handler"](
        {"name": "My Skill", "description": "replacement", "body": "new"})
    assert err is True and "already exists" in text
    text, err = tools["create_skill"]["handler"]({"name": "x"})  # missing body
    assert err is True


def test_load_skill_handler_returns_body_path_and_records_usage(
        tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import curator
    tools = mcp_server._build_tools()
    text, err = tools["load_skill"]["handler"]({"name": "web-research"})
    assert err is False
    assert "# Skill: web-research" in text
    assert "Skill directory:" in text
    assert curator.load_usage()["web-research"]["count"] == 1


def test_mcp_create_respects_manual_skill_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config, store
    cfg = {**config.DEFAULT_CONFIG, "auto_approve": []}
    config.save_config(cfg)
    tools = mcp_server._build_tools()
    text, err = tools["create_skill"]["handler"](
        {"name": "queued-mcp", "description": "d", "body": "body"})
    assert err is False and "awaiting approval" in text
    assert not (config.user_skills_dir() / "queued-mcp" / "SKILL.md").exists()
    assert len(store.list_pending()) == 1
    assert store.list_pending()[0]["origin"] == "mcp"


def test_mcp_load_sees_skill_after_external_manual_approval(
        tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import approvals, config, store
    cfg = {**config.DEFAULT_CONFIG, "auto_approve": []}
    config.save_config(cfg)
    tools = mcp_server._build_tools()
    tools["create_skill"]["handler"](
        {"name": "approved-later", "description": "late helper",
         "body": "UNIQUE-APPROVED-LATER"})
    pending_id = store.list_pending()[0]["id"]

    assert approvals.approve(pending_id)["ok"] is True
    text, err = tools["load_skill"]["handler"]({"name": "approved-later"})

    assert err is False
    assert "UNIQUE-APPROVED-LATER" in text


def test_mcp_improve_refreshes_skill_added_after_server_start(
        tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    cfg = {**config.DEFAULT_CONFIG, "auto_approve": []}
    config.save_config(cfg)
    tools = mcp_server._build_tools()
    skill_dir = config.user_skills_dir() / "external-late"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: external-late\ndescription: late helper\n---\n\nbody\n",
        encoding="utf-8",
    )

    text, err = tools["improve_skill"]["handler"](
        {"target": "external-late", "addition": "new note"})

    assert err is False and "awaiting approval" in text


def test_improve_skill_missing_target_flagged_as_error(tmp_path, monkeypatch):
    """Regression: 'skill not found' must be reported as an error (the old
    prefix heuristic silently treated it as success)."""
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    tools = mcp_server._build_tools()
    text, err = tools["improve_skill"]["handler"](
        {"target": "does-not-exist", "addition": "x"})
    assert err is True


def test_propose_queues_under_default_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    tools = mcp_server._build_tools()
    text, err = tools["propose_action"]["handler"](
        {"category": "cron", "title": "t", "payload": {"type": "prompt"}})
    assert err is False and "Queued" in text


def test_propose_action_queues_shell_without_executing(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import store
    tools = mcp_server._build_tools()
    text, err = tools["propose_action"]["handler"]({
        "category": "shell",
        "title": "Tokscale submit",
        "payload": {
            "command": "bunx tokscale@latest submit",
            "cwd": str(tmp_path),
        },
    })
    assert err is False and "Queued" in text
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0]["category"] == "shell"
    assert pending[0]["payload"]["command"] == "bunx tokscale@latest submit"


def test_propose_action_rejects_unknown_category(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    tools = mcp_server._build_tools()
    text, err = tools["propose_action"]["handler"]({
        "category": "skill",
        "title": "bypass",
        "payload": {"action": "create"},
    })
    assert err is True
    assert "cron" in text.lower() and "shell" in text.lower()


def test_shell_cron_gate_is_case_insensitive(tmp_path, monkeypatch):
    """A capitalised 'Shell' cron payload must NOT auto-apply when only 'cron'
    (not 'shell') is auto-approved."""
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import approvals
    cfg = {"auto_approve": ["cron", "memory", "skill"]}
    status = approvals.propose(
        category="cron", title="t", description="",
        payload={"type": "Shell", "command": "echo hi"}, cfg=cfg)
    assert status["auto"] is False  # queued for human review, not executed


def test_config_helpers(tmp_path):
    cfg = mcp_server.mcp_config_dict()
    assert "birkin" in cfg["mcpServers"]
    assert cfg["mcpServers"]["birkin"]["args"] == ["-m", "birkin", "mcp-serve"]
    p = mcp_server.write_mcp_config(tmp_path / "m.json")
    assert json.loads(p.read_text())["mcpServers"]["birkin"]
    assert mcp_server.birkin_tool_patterns() == ["mcp__birkin__*"]


def test_codex_config_args_define_ephemeral_birkin_server():
    args = mcp_server.codex_config_args(scope="memory")
    joined = " ".join(args)
    assert "mcp_servers.birkin.command" in joined
    assert "mcp_servers.birkin.args" in joined
    assert "mcp_servers.birkin.enabled=true" in joined
    assert "BIRKIN_MCP_SCOPE" in joined
    assert "mcp-serve" in joined
