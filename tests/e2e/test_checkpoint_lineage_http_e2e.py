"""Authenticated real-local-HTTP checkpoint timeline and lineage contract."""

from __future__ import annotations

import http.client
import json
import subprocess
import sys
import threading
from http.server import HTTPServer
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

import pytest

from birkin import checkpoints
from birkin.sandbox import SandboxPolicy
from birkin.sandbox_worktree import WorktreeRunner
from birkin.web import server as web_server


@pytest.fixture
def checkpoint_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[int, str]]:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    server = HTTPServer(("127.0.0.1", 0), web_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], web_server._CAPABILITY_TOKEN
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(port: int, token: str, path: str) -> tuple[int, object]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(
        "GET",
        path,
        headers={
            "Host": "127.0.0.1",
            "X-Birkin-Token": token,
        },
    )
    response = connection.getresponse()
    body = response.read().decode("utf-8")
    connection.close()
    return response.status, json.loads(body)


def test_checkpoint_timeline_and_lineage_use_real_authenticated_http(
    tmp_path: Path,
    checkpoint_server: tuple[int, str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "config", "user.email", "e2e@example.invalid"],
        cwd=workspace,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "E2E"],
        cwd=workspace,
        check=True,
    )
    source = workspace / "main.py"
    source.write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "main.py"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "base"],
        cwd=workspace,
        check=True,
    )
    manager = checkpoints.CheckpointManager()
    manager.begin_tool(workspace, "edit_file", {"path": "main.py"})
    first = manager.list_checkpoints(workspace)[0]["hash"]
    source.write_text("two\n", encoding="utf-8")
    manager.complete_tool("edit_file", failed=False)
    runner = WorktreeRunner(
        workspace,
        sandbox_root=tmp_path / "sandboxes",
    )
    fork = manager.fork(
        workspace,
        first,
        (sys.executable, "-c", "print('alternate')"),
        runner=runner,
        policy=SandboxPolicy(),
    )
    assert fork.returncode == 0
    port, token = checkpoint_server
    query = f"?workspace={quote(str(workspace))}"

    timeline_status, timeline = _get(
        port,
        token,
        f"/api/checkpoints/timeline{query}",
    )
    lineage_status, lineage = _get(
        port,
        token,
        f"/api/checkpoints/lineage{query}",
    )
    unauthenticated, _ = _get(port, "", f"/api/checkpoints/timeline{query}")

    assert timeline_status == 200
    assert lineage_status == 200
    assert unauthenticated == 403
    assert isinstance(timeline, list) and timeline
    assert isinstance(lineage, list) and lineage
    assert lineage[-1]["checkpoint"] == first
