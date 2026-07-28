"""birkin as an MCP server — the vault, offered to any MCP host.

Claude Code (the free, warm backend birkin runs on) can't call birkin's in-loop
tools directly. So birkin *provides* them over MCP: a tiny stdio JSON-RPC 2.0
server exposing the memory-OS, skill authoring, and the approval-gated
``propose_action`` tool. Both the nightly **Morpheus** routine and the gateway
can then point ``claude`` at this server (``--mcp-config``) and call e.g.
``mcp__birkin__memory_write_note`` — keeping everything **free** (Claude
subscription) while preserving birkin's structured, auditable mechanisms.

Only safe, reversible, LLM-free tools are exposed (memory, skills, proposals) —
never shell. Consequential proposals still go through the approval queue.

Transport: newline-delimited JSON-RPC 2.0 over stdin/stdout (the MCP stdio
convention). Pure standard library.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any

_PROTOCOL_VERSION = "2024-11-05"
_SERVER_NAME = "birkin"
_MAX_LINE_BYTES = 4 * 1024 * 1024  # reject absurdly large JSON-RPC frames

def _version() -> str:
    try:
        from . import __version__  # type: ignore
        return str(__version__)
    except Exception:
        return "0.1.0"


# -- tool wiring -----------------------------------------------------------

def _build_tools() -> dict[str, dict[str, Any]]:
    """Return {name: {description, schema, handler(args)->(text, is_error)}}.

    Built with birkin's own context; stdout is muted during setup so a config
    warning can't corrupt the protocol stream.
    """
    with contextlib.redirect_stdout(sys.stderr):
        from . import approvals, config
        from .memory import Memory
        from .skills import build_manager
        from .tools import ToolContext

        cfg = config.load_config()
        memory = Memory(cfg)
        skills = build_manager(cfg)
        ctx = ToolContext(cfg=cfg, client=None, cwd=Path.cwd(),
                          skills=skills, memory=memory)

    tools: dict[str, dict[str, Any]] = {}
    memory_tool_names: set[str] = set()

    # Memory tools (LLM-free; they ignore ctx).
    for t in memory.tools():
        def _mk(tool):
            def handler(args: dict[str, Any]) -> tuple[str, bool]:
                with contextlib.redirect_stdout(sys.stderr):
                    res = tool.fn(args or {}, ctx)
                return res.content, bool(res.is_error)
            return handler
        tools[t.name] = {"description": t.description,
                         "schema": t.input_schema, "handler": _mk(t)}
        memory_tool_names.add(t.name)

    skill_tools = {tool.name: tool for tool in skills.tools(origin="mcp")}

    def _run_skill_tool(name: str, args: dict[str, Any]) -> tuple[str, bool]:
        with contextlib.redirect_stdout(sys.stderr):
            skills.reload_if_changed(debounce=0.0)
            result = skill_tools[name].fn(args, ctx)
        return result.content, bool(result.is_error)

    def _list_skills(_args: dict[str, Any]) -> tuple[str, bool]:
        skills.reload_if_changed(debounce=0.0)
        return skills.index(), False

    def _load_skill(args: dict[str, Any]) -> tuple[str, bool]:
        return _run_skill_tool("load_skill", args)

    def _create_skill(args: dict[str, Any]) -> tuple[str, bool]:
        return _run_skill_tool("create_skill", args)

    def _improve_skill(args: dict[str, Any]) -> tuple[str, bool]:
        return _run_skill_tool(
            "improve_skill", {**args, "name": args.get("target", "")})

    tools["skills_list"] = {
        "description": "List eligible birkin skills with their descriptions.",
        "schema": {"type": "object", "properties": {}},
        "handler": _list_skills}
    tools["load_skill"] = {
        "description": "Load a skill's full instructions and directory path.",
        "schema": {"type": "object", "properties": {
            "name": {"type": "string"}}, "required": ["name"]},
        "handler": _load_skill}

    tools["create_skill"] = {
        "description": "Create a birkin skill (SKILL.md) for a repeatable "
                       "procedure. Provide the full markdown body yourself.",
        "schema": {"type": "object", "properties": {
            "name": {"type": "string"}, "description": {"type": "string"},
            "body": {"type": "string", "description": "Markdown skill body"},
            "tags": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "description", "body"]},
        "handler": _create_skill}
    tools["improve_skill"] = {
        "description": "Append guidance to an existing birkin skill.",
        "schema": {"type": "object", "properties": {
            "target": {"type": "string", "description": "skill name"},
            "addition": {"type": "string"}},
            "required": ["target", "addition"]},
        "handler": _improve_skill}

    # propose_action — consequential actions go through the approval queue.
    def _propose(args: dict[str, Any]) -> tuple[str, bool]:
        if args.get("category", "cron") != "cron":
            return "propose_action only accepts category 'cron'.", True
        payload = args.get("payload", {}) or {}
        if not isinstance(payload, dict):
            return "cron payload must be an object.", True
        with contextlib.redirect_stdout(sys.stderr):
            status = approvals.propose(
                category="cron",
                title=args.get("title", "(untitled)"),
                description=args.get("description", ""),
                payload=payload,
                cfg=cfg, origin="mcp")
        if status.get("auto"):
            if not status.get("ok"):
                return f"Could not apply: {status.get('result')}", True
            return f"Applied: {status.get('result')}", False
        return f"Queued for approval (id {status.get('id')}).", False

    tools["propose_action"] = {
        "description": "Propose a convenience cron job for the user's approval "
                       "(NOT executed now). category 'cron' with payload "
                       "{name,hour,minute,type:'prompt',value}.",
        "schema": {"type": "object", "properties": {
            "category": {"type": "string", "enum": ["cron"]},
            "title": {"type": "string"}, "description": {"type": "string"},
            "payload": {"type": "object"}},
            "required": ["category", "title"]},
        "handler": _propose}

    if os.environ.get("BIRKIN_MCP_SCOPE") == "memory":
        return {name: tool for name, tool in tools.items()
                if name in memory_tool_names}
    return tools


# -- JSON-RPC plumbing -----------------------------------------------------

def _result(rid: Any, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": rid, "result": result})


def _error(rid: Any, code: int, message: str) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": rid,
                       "error": {"code": code, "message": message}})


def handle_message(msg: dict[str, Any], tools: dict[str, dict[str, Any]]):
    """Return a JSON string to send, or None for notifications."""
    method = msg.get("method")
    rid = msg.get("id")
    if method == "initialize":
        client_ver = (msg.get("params") or {}).get("protocolVersion")
        return _result(rid, {
            "protocolVersion": client_ver or _PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": _SERVER_NAME, "version": _version()}})
    if method in ("notifications/initialized", "initialized"):
        return None  # notification
    if method == "ping":
        return _result(rid, {})
    if method == "tools/list":
        return _result(rid, {"tools": [
            {"name": n, "description": t["description"], "inputSchema": t["schema"]}
            for n, t in tools.items()]})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = tools.get(name)
        if tool is None:
            return _result(rid, {"content": [{"type": "text",
                          "text": f"Unknown tool: {name!r}"}], "isError": True})
        try:
            text, is_error = tool["handler"](args)
        except Exception as exc:  # never crash the server
            text, is_error = f"tool {name!r} failed: {exc}", True
        return _result(rid, {"content": [{"type": "text", "text": str(text)}],
                             "isError": bool(is_error)})
    if rid is None:
        return None  # unknown notification — ignore
    return _error(rid, -32601, f"method not found: {method}")


def serve(stdin=None, stdout=None) -> int:
    """Run the MCP server loop until stdin closes."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    tools = _build_tools()

    def _emit(text: str) -> None:
        stdout.write(text + "\n")
        stdout.flush()

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        if len(line.encode("utf-8", "surrogatepass")) > _MAX_LINE_BYTES:
            _emit(_error(None, -32700, "request too large"))
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _emit(_error(None, -32700, "parse error"))  # JSON-RPC 2.0 §5
            continue
        out = handle_message(msg, tools)
        if out is not None:
            _emit(out)
    return 0


# -- launch config helpers (so claude can spawn this server) ---------------

def mcp_config_dict() -> dict[str, Any]:
    """An ``--mcp-config`` payload that launches THIS birkin as the server."""
    return {"mcpServers": {_SERVER_NAME: {
        "command": sys.executable, "args": ["-m", "birkin", "mcp-serve"]}}}


def write_mcp_config(path: Path) -> Path:
    path.write_text(json.dumps(mcp_config_dict(), indent=2), encoding="utf-8")
    return path


def codex_config_args(*, scope: str = "full") -> list[str]:
    server = mcp_config_dict()["mcpServers"][_SERVER_NAME]
    args = [
        "-c", f"mcp_servers.{_SERVER_NAME}.command="
              f"{json.dumps(server['command'])}",
        "-c", f"mcp_servers.{_SERVER_NAME}.args="
              f"{json.dumps(server['args'])}",
        "-c", f"mcp_servers.{_SERVER_NAME}.enabled=true",
    ]
    if scope == "memory":
        args += [
            "-c",
            f"mcp_servers.{_SERVER_NAME}.env={{ BIRKIN_MCP_SCOPE = "
            '"memory" }',
        ]
    return args


def birkin_tool_patterns() -> list[str]:
    """`--allowedTools` patterns for birkin's MCP tools (server-name prefixed)."""
    return [f"mcp__{_SERVER_NAME}__*"]
