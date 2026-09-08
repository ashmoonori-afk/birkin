from __future__ import annotations

import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from birkin.proc import kill_tree


def _send(process: subprocess.Popen[str], message: dict) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()


def _read(messages: queue.Queue[str]) -> dict:
    return json.loads(messages.get(timeout=3))


def _read_response(messages: queue.Queue[str], request_id: int) -> tuple[dict, list[int]]:
    progress = []
    while True:
        message = _read(messages)
        if message.get("method") == "notifications/progress":
            progress.append(message["params"]["progress"])
            continue
        if message.get("id") == request_id:
            return message, progress


def test_research_progress_cancel_and_follow_up_ping_over_stdio(tmp_path: Path) -> None:
    script = tmp_path / "server.py"
    script.write_text(
        """
import time
from birkin import mcp_server

def handler(args, *, abort=None, emit=None):
    if args.get("fast"):
        emit("moirai.phase", {"title": "Report"})
        return "complete", False
    step = 0
    while not abort.is_set():
        step += 1
        emit("moirai.phase", {"title": "Collect"})
        time.sleep(0.01)
    return "cancelled", True

mcp_server._build_tools = lambda: {"research_run": {
    "description": "test", "schema": {}, "handler": handler,
}}
raise SystemExit(mcp_server.serve())
""".strip(),
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [sys.executable, str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert process.stdout is not None
    messages: queue.Queue[str] = queue.Queue()
    reader = threading.Thread(
        target=lambda: [messages.put(line) for line in process.stdout], daemon=True,
    )
    reader.start()
    try:
        assert process.stdin is not None
        process.stdin.write("[]\n")
        process.stdin.flush()
        assert _read(messages)["error"]["code"] == -32600
        _send(process, {
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {
                "name": "research_run", "arguments": {"question": "q"},
                "_meta": {"progressToken": "research-progress"},
            },
        })
        progress = _read(messages)
        assert progress["method"] == "notifications/progress"
        assert progress["params"]["progressToken"] == "research-progress"
        assert progress["params"]["message"] == "출처 수집"

        _send(process, {
            "jsonrpc": "2.0", "method": "notifications/cancelled",
            "params": {"requestId": ["invalid"]},
        })

        _send(process, {
            "jsonrpc": "2.0", "method": "notifications/cancelled",
            "params": {"requestId": 7, "reason": "user cancelled"},
        })
        _send(process, {"jsonrpc": "2.0", "id": 8, "method": "ping"})
        ping, buffered_progress = _read_response(messages, 8)
        assert ping == {"jsonrpc": "2.0", "id": 8, "result": {}}
        assert buffered_progress == sorted(set(buffered_progress))

        _send(process, {"jsonrpc": "2.0", "id": 9, "method": "ping"})
        assert _read_response(messages, 9)[0]["id"] == 9

        time.sleep(0.1)
        _send(process, {
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {"name": "research_run", "arguments": {"fast": True}},
        })
        no_progress = _read(messages)
        assert no_progress["id"] == 10
        assert no_progress["result"]["content"][0]["text"] == "complete"
    finally:
        if process.stdin is not None:
            process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            kill_tree(process)
            process.wait(timeout=5)
    assert process.returncode == 0


def test_research_stops_when_stdio_client_disconnects(tmp_path: Path) -> None:
    stopped = tmp_path / "provider-stopped"
    script = tmp_path / "disconnect_server.py"
    script.write_text(
        f"""
import time
from pathlib import Path
from birkin import mcp_server

def handler(args, *, abort=None, emit=None):
    emit("moirai.phase", {{"title": "Collect"}})
    while not abort.is_set():
        time.sleep(0.01)
    Path({str(stopped)!r}).write_text("stopped", encoding="utf-8")
    return "cancelled", True

mcp_server._build_tools = lambda: {{"research_run": {{
    "description": "test", "schema": {{}}, "handler": handler,
}}}}
raise SystemExit(mcp_server.serve())
""".strip(),
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [sys.executable, str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert process.stdin is not None and process.stdout is not None
    try:
        _send(process, {
            "jsonrpc": "2.0", "id": 11, "method": "tools/call",
            "params": {
                "name": "research_run", "arguments": {"question": "q"},
                "_meta": {"progressToken": "disconnect-progress"},
            },
        })
        progress = json.loads(process.stdout.readline())
        assert progress["method"] == "notifications/progress"

        process.stdin.close()
        process.wait(timeout=5)

        assert process.returncode == 0
        assert stopped.read_text(encoding="utf-8") == "stopped"
    finally:
        if process.poll() is None:
            kill_tree(process)
            process.wait(timeout=5)
