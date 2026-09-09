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
from dataclasses import replace
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

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
        from . import approvals, config, presets
        from .memory import Memory
        from .skills import build_manager
        from .tools import ToolContext, documents, egress, market, research

        cfg = config.load_config()
        effective_model = os.environ.get("BIRKIN_MCP_MODEL") or cfg.get("model")
        cfg = {**cfg, "model": effective_model}
        disabled = set(cfg.get("disabled_tools", []) or [])
        disabled |= presets.deny_tools(effective_model, cfg)
        memory = Memory(cfg)
        skills = build_manager(cfg)
        ctx = ToolContext(cfg=cfg, client=None, cwd=Path.cwd(),
                          skills=skills, memory=memory)

    tools: dict[str, dict[str, Any]] = {}
    memory_tool_names: set[str] = set()
    market_tool_names: set[str] = set()
    egress_tool_names: set[str] = set()

    def _mk(tool):
        def handler(
            args: dict[str, Any], *, abort=None, emit=None,
        ) -> tuple[str, bool]:
            call_ctx = replace(ctx, abort=abort, emit=emit)
            with contextlib.redirect_stdout(sys.stderr):
                res = tool.fn(args or {}, call_ctx)
            return res.content, bool(res.is_error)
        return handler

    # Memory tools (LLM-free; they ignore ctx).
    for t in memory.tools():
        tools[t.name] = {"description": t.description,
                         "schema": t.input_schema, "handler": _mk(t)}
        memory_tool_names.add(t.name)

    # Read-only structured market quotes are safe for every full MCP session.
    scope = os.environ.get("BIRKIN_MCP_SCOPE", "full")
    if scope == "full":
        for t in market.tools():
            tools[t.name] = {
                "description": t.description,
                "schema": t.input_schema,
                "handler": _mk(t),
            }
            market_tool_names.add(t.name)

        egress_cfg = cfg.get("egress", {})
        if (isinstance(egress_cfg, dict)
                and egress_cfg.get("enabled") is True):
            for t in egress.tools():
                tools[t.name] = {
                    "description": t.description,
                    "schema": t.input_schema,
                    "handler": _mk(t),
                }
                egress_tool_names.add(t.name)

    workspace_tool_names: set[str] = set()
    if scope == "workspace":
        for tool in documents.tools() + research.tools():
            if tool.name in {
                "inspect_document",
                "office_job_request",
                "work_item_request",
                "research_run",
            }:
                tools[tool.name] = {
                    "description": tool.description,
                    "schema": tool.input_schema,
                    "handler": _mk(tool),
                }
                workspace_tool_names.add(tool.name)

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
        category = str(args.get("category", "cron")).strip().lower()
        if category not in {"cron", "shell"}:
            return "propose_action only accepts category 'cron' or 'shell'.", True
        payload = args.get("payload", {}) or {}
        if not isinstance(payload, dict):
            return f"{category} payload must be an object.", True
        if category == "shell" and not str(payload.get("command", "")).strip():
            return "shell payload requires a command.", True
        with contextlib.redirect_stdout(sys.stderr):
            status = approvals.propose(
                category=category,
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
        "description": "Propose a cron job or shell command for the user's "
                       "approval (NOT executed now). Use category 'shell' with "
                       "payload {command,cwd} when a requested command cannot "
                       "run inside the child sandbox.",
        "schema": {"type": "object", "properties": {
            "category": {"type": "string", "enum": ["cron", "shell"]},
            "title": {"type": "string"}, "description": {"type": "string"},
            "payload": {"type": "object"}},
            "required": ["category", "title"]},
        "handler": _propose}

    # companion_propose — natural-language check-ins, same approval hook.
    # Registered only once the user has bound a context (opt-in feature).
    def _companion_propose(args: dict[str, Any]) -> tuple[str, bool]:
        from . import companion
        try:
            with contextlib.redirect_stdout(sys.stderr):
                status = companion.propose_checkin(
                    outcome=str(args.get("outcome", "")),
                    check_in_at=str(args.get("check_in_at", "")),
                    next_action=str(args.get("next_action", "")),
                    context_id=str(args.get("context_id", "")),
                    cfg=cfg, origin="mcp")
        except companion.CompanionError as exc:
            return f"Cannot propose a check-in: {exc}", True
        if status.get("auto"):
            if not status.get("ok"):
                return f"Could not schedule: {status.get('result')}", True
            return f"Scheduled: {status.get('result')}", False
        return (f"Queued for the user's approval (id {status.get('id')}). "
                f"Nothing is scheduled unless they approve it."), False

    if (config.birkin_home() / "companion" / "state.json").is_file():
        tools["companion_propose"] = {
            "description": "Propose a follow-up check-in for something the "
                           "user explicitly committed to do at an agreed time "
                           "(NOT executed now — queued for their approval). "
                           "check_in_at is ISO 8601 with a UTC offset.",
            "schema": {"type": "object", "properties": {
                "outcome": {"type": "string"},
                "check_in_at": {"type": "string"},
                "next_action": {"type": "string"},
                "context_id": {"type": "string"}},
                "required": ["outcome", "check_in_at"]},
            "handler": _companion_propose}

    skill_tool_names = {
        "skills_list",
        "load_skill",
        "create_skill",
        "improve_skill",
    }
    groups = {
        **{name: "memory" for name in memory_tool_names},
        **{name: "web" for name in market_tool_names},
        **{name: "egress" for name in egress_tool_names},
        **{
            name: (
                "approvals"
                if name in {"office_job_request", "work_item_request"}
                else "documents"
                if name == "inspect_document"
                else "research"
            )
            for name in workspace_tool_names
        },
        **{name: "skills" for name in skill_tool_names},
        "propose_action": "approvals",
        "companion_propose": "companion",
    }
    allowed = {
        name: tool
        for name, tool in tools.items()
        if name not in disabled and groups.get(name) not in disabled
        and not (name == "office_job_request" and "documents" in disabled)
    }
    if os.environ.get("BIRKIN_MCP_SCOPE") == "memory":
        return {
            name: tool
            for name, tool in allowed.items()
            if name in memory_tool_names
        }
    if scope == "workspace":
        workspace_allowed = {
            "memory_search", "memory_get_note", "memory_related",
            "skills_list", "load_skill", "inspect_document",
            "office_job_request", "work_item_request", "research_run",
        }
        return {name: tool for name, tool in allowed.items() if name in workspace_allowed}
    return allowed


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
        raw_params = msg.get("params")
        params = raw_params if isinstance(raw_params, dict) else {}
        name = params.get("name")
        if not isinstance(name, str):
            return _result(rid, {"content": [{"type": "text",
                            "text": "Unknown tool: missing name"}],
                            "isError": True})
        raw_args = params.get("arguments")
        args = raw_args if isinstance(raw_args, dict) else {}
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


def _tool_call_result(
    msg: dict[str, Any], tools: dict[str, dict[str, Any]], *, abort=None, emit=None,
) -> str:
    rid = msg.get("id")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    name = params.get("name")
    tool = tools.get(name) if isinstance(name, str) else None
    if tool is None:
        return handle_message(msg, tools) or _error(rid, -32603, "tool call failed")
    try:
        text, is_error = tool["handler"](
            params.get("arguments") if isinstance(params.get("arguments"), dict) else {},
            abort=abort,
            emit=emit,
        )
    except Exception as exc:
        text, is_error = f"tool {name!r} failed: {exc}", True
    return _result(rid, {
        "content": [{"type": "text", "text": str(text)}],
        "isError": bool(is_error),
    })


def serve(stdin=None, stdout=None) -> int:
    """Run the MCP server loop until stdin closes."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    tools = _build_tools()
    output_lock = threading.Lock()
    active: dict[str | int, tuple[threading.Event, threading.Thread]] = {}
    active_lock = threading.Lock()

    def _emit(text: str) -> None:
        with output_lock:
            stdout.write(text + "\n")
            stdout.flush()

    def _start_research(msg: dict[str, Any]) -> bool:
        rid = msg.get("id")
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        if params.get("name") != "research_run" or isinstance(rid, bool) or not isinstance(rid, (str, int)):
            return False
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        token = meta.get("progressToken")
        if isinstance(token, bool) or not isinstance(token, (str, int)):
            token = None
        abort = threading.Event()

        def run() -> None:
            progress = 0
            progress_lock = threading.Lock()

            def emit(event: str, payload: dict[str, Any]) -> None:
                nonlocal progress
                if token is None or abort.is_set():
                    return
                phase = str(payload.get("title") or "").casefold()
                phase_message = next((
                    label for key, label in (
                        ("plan", "조사 계획 수립"),
                        ("collect", "출처 수집"),
                        ("analy", "근거 분석"),
                        ("challenge", "반증 검토"),
                        ("report", "결과 정리"),
                    ) if key in phase
                ), None)
                message = phase_message or {
                    "subagent.start": "연구 작업 시작",
                    "subagent.done": "연구 작업 완료",
                    "moirai.cached": "저장된 연구 결과 확인",
                }.get(event)
                if message is None:
                    return
                with progress_lock:
                    progress += 1
                    _emit(json.dumps({
                        "jsonrpc": "2.0",
                        "method": "notifications/progress",
                        "params": {
                            "progressToken": token,
                            "progress": progress,
                            "message": message,
                        },
                    }))

            try:
                response = _tool_call_result(msg, tools, abort=abort, emit=emit)
                with active_lock:
                    if not abort.is_set():
                        _emit(response)
            finally:
                with active_lock:
                    active.pop(rid, None)

        thread = threading.Thread(target=run, name=f"mcp-research-{rid}", daemon=True)
        with active_lock:
            if active:
                _emit(_error(rid, -32000, "research request already in progress"))
                return True
            active[rid] = (abort, thread)
        thread.start()
        return True

    while True:
        line = stdin.readline(_MAX_LINE_BYTES + 1)
        if line == "":
            break
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped.encode("utf-8", "surrogatepass")) > _MAX_LINE_BYTES:
            _emit(_error(None, -32700, "request too large"))
            while line and not line.endswith("\n"):
                line = stdin.readline(_MAX_LINE_BYTES + 1)
            continue
        try:
            msg = json.loads(stripped)
        except json.JSONDecodeError:
            _emit(_error(None, -32700, "parse error"))  # JSON-RPC 2.0 §5
            continue
        if not isinstance(msg, dict):
            _emit(_error(None, -32600, "invalid request"))
            continue
        if msg.get("method") == "notifications/cancelled":
            params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
            request_id = params.get("requestId")
            if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
                continue
            with active_lock:
                running = active.get(request_id)
            if running is not None:
                running[0].set()
            continue
        if msg.get("method") == "tools/call" and _start_research(msg):
            continue
        with active_lock:
            busy = bool(active)
        if busy and msg.get("method") == "tools/call":
            _emit(_error(msg.get("id"), -32000, "research request in progress"))
            continue
        out = handle_message(msg, tools)
        if out is not None:
            _emit(out)
    with active_lock:
        running = list(active.values())
    for abort, _thread in running:
        abort.set()
    for _abort, thread in running:
        thread.join()
    return 0


# -- launch config helpers (so claude can spawn this server) ---------------

def mcp_config_dict(*, model: Optional[str] = None,
                    scope: str = "full") -> dict[str, Any]:
    """An ``--mcp-config`` payload that launches THIS birkin as the server."""
    from . import config

    server: dict[str, Any] = {
        "command": sys.executable,
        "args": ["-m", "birkin", "mcp-serve"],
    }
    env: dict[str, str] = {
        "BIRKIN_HOME": str(config.birkin_home()),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    if model:
        env["BIRKIN_MCP_MODEL"] = model
    if scope != "full":
        env["BIRKIN_MCP_SCOPE"] = scope
    if env:
        server["env"] = env
    return {"mcpServers": {_SERVER_NAME: server}}


def write_mcp_config(path: Path, *, model: Optional[str] = None,
                     scope: str = "full") -> Path:
    payload = mcp_config_dict(model=model, scope=scope)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def codex_config_args(*, scope: str = "full",
                      model: Optional[str] = None) -> list[str]:
    server = mcp_config_dict(model=model, scope=scope)["mcpServers"][_SERVER_NAME]
    args = [
        "-c", f"mcp_servers.{_SERVER_NAME}.command="
              f"{json.dumps(server['command'])}",
        "-c", f"mcp_servers.{_SERVER_NAME}.args="
              f"{json.dumps(server['args'])}",
        "-c", f"mcp_servers.{_SERVER_NAME}.enabled=true",
        "-c", f"mcp_servers.{_SERVER_NAME}.startup_timeout_sec=30",
    ]
    env = server.get("env") or {}
    if env:
        values = ", ".join(
            f"{key} = {json.dumps(value)}"
            for key, value in sorted(env.items())
        )
        args += [
            "-c",
            f"mcp_servers.{_SERVER_NAME}.env={{ {values} }}",
        ]
    return args


def birkin_tool_patterns() -> list[str]:
    """`--allowedTools` patterns for birkin's MCP tools (server-name prefixed)."""
    return [f"mcp__{_SERVER_NAME}__*"]
