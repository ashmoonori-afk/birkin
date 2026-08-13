from __future__ import annotations

import http.client
import json
import os
import threading
from http.server import HTTPServer

import pytest

from birkin import agentruns, config, promptgate, store
from birkin.web import server as web_server


@pytest.fixture
def srv():
    httpd = HTTPServer(("127.0.0.1", 0), web_server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1], web_server._TOKEN
    finally:
        httpd.shutdown()
        httpd.server_close()


def request(srv, method, path, payload=None, *, token=True):
    port, capability = srv
    headers = {"Host": "127.0.0.1"}
    if token:
        headers["X-Birkin-Token"] = capability
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    data = response.read()
    headers_out = dict(response.getheaders())
    conn.close()
    return response.status, headers_out, data


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/context"),
    ("GET", "/api/approvals/000000000000/diff"),
    ("GET", "/api/events"),
    ("GET", "/api/config"),
    ("GET", "/api/checkpoints"),
    ("POST", "/api/checkpoints/abcd/restore"),
])
def test_ide_endpoints_require_token(srv, method, path):
    status, _, _ = request(srv, method, path, {} if method == "POST" else None,
                           token=False)
    assert status == 403


def test_context_persists_and_reaches_next_prompt(srv):
    context = {
        "file": "src/app.py",
        "range": {"start": {"line": 2, "character": 1},
                  "end": {"line": 4, "character": 8}},
        "selection_text": "print('hello')",
        "workspace": "C:/work/demo",
    }
    status, _, body = request(srv, "POST", "/api/context", context)
    assert status == 200 and json.loads(body) == {"ok": True}
    assert store._read_json(config.birkin_home() / "ide_context.json", {}) == context
    assembled = promptgate.compose_main({"neurosis_auto": False}, persona_text="")
    assert "IDE context" in assembled
    assert "src/app.py" in assembled and "print('hello')" in assembled
    assert not (config.birkin_home() / "ide_context.json").exists()


@pytest.mark.parametrize("payload", [None, [], {"file": "x"}, {
    "file": "x", "range": {}, "selection_text": 1, "workspace": "w"}])
def test_context_rejects_malformed(srv, payload):
    status, _, _ = request(srv, "POST", "/api/context", payload)
    assert status == 400


def test_approval_diff_and_unknown(srv):
    rec = store.add_pending(category="harness", title="edit", description="",
                            payload={"file": "demo.txt", "before": "old\n",
                                     "after": "new\n"})
    status, headers, body = request(
        srv, "GET", f"/api/approvals/{rec['id']}/diff")
    text = body.decode()
    assert status == 200 and headers["Content-Type"].startswith("text/x-diff")
    assert "--- a/demo.txt" in text and "+++ b/demo.txt" in text
    assert "-old" in text and "+new" in text
    assert request(srv, "GET", "/api/approvals/000000000000/diff")[0] == 404
    assert request(srv, "GET", "/api/approvals/not-valid/diff")[0] == 400


def test_config_is_safe_subset(srv, monkeypatch):
    monkeypatch.setattr(web_server.config, "load_config", lambda: {
        "auto_approve": ["memory"], "disabled_tools": ["run_shell"],
        "checkpoints": True, "model": "safe-model", "provider": "openai",
        "api_key": "TOP-SECRET", "channels": {"telegram": {"token": "NO"}},
    })
    status, _, body = request(srv, "GET", "/api/config")
    payload = json.loads(body)
    assert status == 200
    assert payload == {"auto_approve": ["memory"],
                       "disabled_tools": ["run_shell"], "checkpoints": True,
                       "model": "safe-model", "provider": "openai"}
    assert b"SECRET" not in body and b"token" not in body.lower()


def test_checkpoints_list_restore_and_malformed(srv, monkeypatch):
    class Manager:
        def list_checkpoints(self, workdir):
            return [{"hash": "a" * 40, "short": "a" * 7,
                     "date": "2026-01-01T00:00:00Z", "reason": "before edit"}]
        def restore(self, workdir, checkpoint):
            return (True, "restored files") if checkpoint == "a" * 40 else (False, "bad")
    monkeypatch.setattr(web_server, "_checkpoint_manager", lambda: Manager())
    status, _, body = request(srv, "GET", "/api/checkpoints")
    assert status == 200 and json.loads(body)[0]["short"] == "aaaaaaa"
    status, _, body = request(
        srv, "POST", f"/api/checkpoints/{'a' * 40}/restore", {})
    assert status == 200 and json.loads(body)["ok"] is True
    assert request(srv, "POST", "/api/checkpoints/nope/restore", {})[0] == 400


def test_events_streams_agent_and_approval_state(srv):
    run = agentruns.register_run("test stream")
    agentruns.progress(run["id"], "compiled cleanly")
    pending = store.add_pending(category="cron", title="review", description="",
                                payload={})
    port, token = srv
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request("GET", "/api/events", headers={"Host": "127.0.0.1",
                                                  "X-Birkin-Token": token})
    response = conn.getresponse()
    assert response.status == 200
    assert response.getheader("Content-Type") == "text/event-stream"
    lines = []
    while len(lines) < 12:
        line = response.fp.readline().decode().strip()
        if line:
            lines.append(line)
        if any("compiled cleanly" in item for item in lines) and any(
                pending["id"] in item for item in lines):
            break
    conn.close()
    joined = "\n".join(lines)
    assert "compiled cleanly" in joined
    assert pending["id"] in joined


def test_run_persists_private_web_session(monkeypatch):
    class StoppingServer:
        def __init__(self, address, handler):
            self.server_address = (address[0], 54321)
        def serve_forever(self):
            raise KeyboardInterrupt
        def server_close(self):
            pass
    monkeypatch.setattr(web_server, "HTTPServer", StoppingServer)
    web_server.run(port=0, open_browser=False)
    path = config.birkin_home() / "web_session.json"
    assert store._read_json(path, {}) == {"port": 54321, "token": web_server._TOKEN}
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
