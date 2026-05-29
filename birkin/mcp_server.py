"""birkin as an MCP server — exposes birkin's structured self-improvement tools.

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
import sys
from pathlib import Path
from typing import Any

_PROTOCOL_VERSION = "2024-11-05"
_SERVER_NAME = "birkin"
_MAX_LINE_BYTES = 4 * 1024 * 1024  # reject absurdly large JSON-RPC frames

# apply_skill_proposal returns a human string; success starts with one of these.
# Anything else (missing fields, "skill not found", "unknown action") is an error.
_SKILL_OK_PREFIXES = ("created skill", "appended learned note")


def _skill_is_error(out: str) -> bool:
    return not str(out).strip().lower().startswith(_SKILL_OK_PREFIXES)


@contextlib.contextmanager
def _stdout_to_stderr():
    """Keep birkin's stray prints off the JSON-RPC stdout channel."""
    saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = saved


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
    with _stdout_to_stderr():
        from . import approvals, config
        from .memory import Memory
        from .skills import build_manager
        from .skills.manager import apply_skill_proposal
        from .tools import ToolContext

        cfg = config.load_config()
        memory = Memory(cfg)
        skills = build_manager(cfg)
        ctx = ToolContext(cfg=cfg, client=None, cwd=Path.cwd(),
                          skills=skills, memory=memory)

    tools: dict[str, dict[str, Any]] = {}

    # Memory tools (LLM-free; they ignore ctx).
    for t in memory.tools():
        def _mk(tool):
            def handler(args: dict[str, Any]) -> tuple[str, bool]:
                with _stdout_to_stderr():
                    res = tool.fn(args or {}, ctx)
                return res.content, bool(res.is_error)
            return handler
        tools[t.name] = {"description": t.description,
                         "schema": t.input_schema, "handler": _mk(t)}

    # create_skill / improve_skill — applied directly (reversible, content from
    # the caller, no birkin LLM call).
    def _create_skill(args: dict[str, Any]) -> tuple[str, bool]:
        with _stdout_to_stderr():
            out = apply_skill_proposal({"action": "create",
                                        "name": args.get("name", ""),
                                        "description": args.get("description", ""),
                                        "body": args.get("body", ""),
                                        "tags": args.get("tags") or []})
        return out, _skill_is_error(out)

    def _improve_skill(args: dict[str, Any]) -> tuple[str, bool]:
        with _stdout_to_stderr():
            out = apply_skill_proposal({"action": "improve",
                                        "target": args.get("target", ""),
                                        "addition": args.get("addition", "")})
        return out, _skill_is_error(out)

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
        with _stdout_to_stderr():
            status = approvals.propose(
                category=args.get("category", "cron"),
                title=args.get("title", "(untitled)"),
                description=args.get("description", ""),
                payload=args.get("payload", {}) or {},
                cfg=cfg, origin="morpheus")  # reuse the config loaded above
        if status.get("auto"):
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
        if len(line) > _MAX_LINE_BYTES:
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


def birkin_tool_patterns() -> list[str]:
    """`--allowedTools` patterns for birkin's MCP tools (server-name prefixed)."""
    return [f"mcp__{_SERVER_NAME}__*"]
