"""Agent2Agent v1.0: let another agent hand birkin a task.

A2A is JSON-RPC 2.0 over HTTP plus a discovery document at
``/.well-known/agent-card.json``. birkin already serves loopback HTTP and
already hand-rolls JSON-RPC for its MCP server, so the protocol costs no
dependency -- which is the only reason it can exist under
``dependencies = []`` at all. The reference SDK would have brought FastAPI,
uvicorn, pydantic and httpx for a wire format that fits in this file.

**Off unless asked.** This endpoint accepts work from another program. Nobody
acquires that by upgrading: while ``a2a_enabled`` is false every A2A path is a
plain 404, indistinguishable from a birkin that never had the feature. Only a
real boolean turns it on -- a stray ``"false"`` in a hand-edited config must
not open an inbound execution surface.

What is deliberately NOT implemented, and is advertised as absent in the card
rather than half-built: streaming (``message/stream``) and push notifications.
A peer that trusts a capability we do not have is worse off than one that sees
it declared false.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

PROTOCOL_VERSION = "1.0"

# JSON-RPC reserved codes, then A2A's own.
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TASK_NOT_FOUND = -32001
TASK_NOT_CANCELABLE = -32002

# A finished task is kept only long enough for the peer to fetch it.
_MAX_TASKS = 100

_tasks: "dict[str, dict[str, Any]]" = {}
_lock = threading.Lock()


def enabled(cfg: dict[str, Any]) -> bool:
    """True only for a real ``True``.

    Not truthiness: ``"false"`` is a string a human types into config.json by
    hand, and it must not open an inbound execution surface.
    """
    return (cfg or {}).get("a2a_enabled") is True


def agent_card(base_url: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """The discovery document a peer fetches before talking to us."""
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "name": str((cfg or {}).get("a2a_name") or "birkin"),
        "description": ("A self-improving CLI agent workspace with skills, "
                        "subagents and memory."),
        "url": f"{base_url.rstrip('/')}/a2a",
        "preferredTransport": "JSONRPC",
        "version": _version(),
        "capabilities": {
            # Declared false because they are not implemented. A card that
            # claims a capability it lacks breaks the peer, not us.
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{
            "id": "chat",
            "name": "General assistance",
            "description": ("Answer a question or carry out a task using "
                            "birkin's tools, skills and memory."),
            "tags": ["chat", "tools", "memory"],
        }],
    }


def _version() -> str:
    from .. import __version__
    return __version__


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def _text_of(message: Any) -> str:
    """The text a peer sent, from A2A's parts list."""
    if not isinstance(message, dict):
        return ""
    pieces = []
    for part in message.get("parts") or []:
        if isinstance(part, dict) and part.get("kind") == "text":
            pieces.append(str(part.get("text") or ""))
    return "\n".join(p for p in pieces if p).strip()


def _remember(task: dict[str, Any]) -> None:
    with _lock:
        _tasks[task["id"]] = task
        # Bounded: a long-lived gateway must not accumulate every task it was
        # ever handed.
        while len(_tasks) > _MAX_TASKS:
            _tasks.pop(next(iter(_tasks)))


def _task(task_id: str, state: str, text: str, context_id: str) -> dict[str, Any]:
    return {
        "id": task_id,
        "contextId": context_id,
        "kind": "task",
        "status": {"state": state,
                   "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                              time.gmtime())},
        "artifacts": [{
            "artifactId": uuid.uuid4().hex,
            "parts": [{"kind": "text", "text": text}],
        }] if text else [],
    }


def _message_send(request_id: Any, params: dict[str, Any],
                  run: Callable[[str], str]) -> dict[str, Any]:
    text = _text_of(params.get("message"))
    if not text:
        return _error(request_id, INVALID_PARAMS,
                      "message.parts must carry at least one text part")
    task_id = uuid.uuid4().hex
    context_id = str(params.get("contextId") or uuid.uuid4().hex)
    try:
        reply = run(text)
        task = _task(task_id, "completed", str(reply or ""), context_id)
    except Exception as exc:                    # noqa: BLE001 - boundary
        # A peer gets a failed TASK, never a transport error: the RPC itself
        # succeeded, and "your task failed" is the answer it can act on.
        task = _task(task_id, "failed", f"birkin could not answer: {exc}",
                     context_id)
    _remember(task)
    return {"jsonrpc": "2.0", "id": request_id, "result": task}


def _tasks_get(request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        task = _tasks.get(str(params.get("id") or ""))
    if task is None:
        return _error(request_id, TASK_NOT_FOUND, "task not found")
    return {"jsonrpc": "2.0", "id": request_id, "result": task}


def _tasks_cancel(request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        task = _tasks.get(str(params.get("id") or ""))
    if task is None:
        return _error(request_id, TASK_NOT_FOUND, "task not found")
    if task["status"]["state"] in ("completed", "failed", "canceled"):
        return _error(request_id, TASK_NOT_CANCELABLE,
                      f"task is already {task['status']['state']}")
    with _lock:
        task["status"]["state"] = "canceled"
    return {"jsonrpc": "2.0", "id": request_id, "result": task}


def handle(request: Any, *, run: Callable[[str], str]) -> dict[str, Any]:
    """Answer one JSON-RPC request. ``run`` turns text into birkin's reply."""
    if not isinstance(request, dict):
        return _error(None, INVALID_REQUEST, "request must be a JSON object")
    request_id = request.get("id")
    method = str(request.get("method") or "")
    params = request.get("params")
    params = params if isinstance(params, dict) else {}
    if method == "message/send":
        return _message_send(request_id, params, run)
    if method == "tasks/get":
        return _tasks_get(request_id, params)
    if method == "tasks/cancel":
        return _tasks_cancel(request_id, params)
    return _error(request_id, METHOD_NOT_FOUND, f"unknown method {method!r}")
