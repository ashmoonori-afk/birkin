from __future__ import annotations

import http.client
import json
import threading
from http.server import HTTPServer

import pytest

from birkin import agentruns, approvals, config, store
from birkin.web import server as web_server
from tests.local_http_support import local_http_timeout


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


def request(srv, method: str, path: str, payload=None, *, token=True,
            host="127.0.0.1"):
    port, capability = srv
    headers = {"Host": host}
    if token:
        headers["X-Birkin-Token"] = capability
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    conn = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=local_http_timeout()
    )
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    try:
        parsed = json.loads(data) if data else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        parsed = data.decode("utf-8", "replace")
    return response.status, parsed


def test_run_listing_shape_and_detail_marks_waiting_approval(srv):
    run = agentruns.register_run("deploy the release")
    agentruns.progress(run["id"], "prepared patch")
    store.add_pending(
        category="shell", title="publish", description="run publisher",
        payload={"command": "publish", "run_id": run["id"]},
        origin=f"agent:{run['id']}",
    )

    status, payload = request(srv, "GET", "/api/agent-runs")
    assert status == 200
    listed = payload["runs"][0]
    assert set(listed) >= {
        "id", "task", "status", "ui_state", "terminal", "started_at",
        "last_heartbeat", "heartbeat_age", "parent_id", "pending_approvals",
    }
    assert listed["status"] == "waiting-approval"
    assert listed["ui_state"] == "waiting_human"
    assert listed["terminal"] is False
    assert listed["pending_approvals"] == 1

    status, detail = request(srv, "GET", f"/api/agent-runs/{run['id']}")
    assert status == 200
    assert detail["events"][0]["text"] == "prepared patch"
    assert detail["approvals"][0]["category"] == "shell"


@pytest.mark.parametrize("path", [
    "/api/agent-runs", "/api/agent-runs/000000000000",
    "/api/actions/000000000000/receipt",
])
def test_console_reads_require_capability(srv, path):
    assert request(srv, "GET", path, token=False)[0] == 403


def test_approve_reject_transitions_and_action_receipt(srv, monkeypatch):
    monkeypatch.setattr(
        approvals, "execute_action", lambda category, payload: "exit 0: shipped")
    approved = store.add_pending(
        category="shell", title="ship", description="", payload={"command": "ship"})
    rejected = store.add_pending(
        category="cron", title="later", description="", payload={"name": "later"})

    assert request(srv, "POST", "/api/approvals", {
        "id": approved["id"], "action": "approve"}) == (
            200, {"ok": True, "result": "exit 0: shipped"})
    assert store.get_pending(approved["id"])["status"] == "approved"

    status, receipt = request(
        srv, "GET", f"/api/actions/{approved['id']}/receipt")
    assert status == 200
    assert receipt == {
        "id": approved["id"], "category": "shell", "status": "approved",
        "executed_at": store.get_pending(approved["id"])["resolved_at"],
        "receipt": "exit 0: shipped",
    }

    assert request(srv, "POST", "/api/approvals", {
        "id": rejected["id"], "action": "reject"}) == (200, {"ok": True})
    assert store.get_pending(rejected["id"])["status"] == "rejected"
    assert request(srv, "GET", f"/api/actions/{rejected['id']}/receipt")[0] == 409


def test_steer_abort_resume_state_machine(srv):
    run = agentruns.register_run("long task")
    endpoint = f"/api/agent-runs/{run['id']}/control"

    status, steered = request(srv, "POST", endpoint, {
        "action": "steer", "text": "focus on tests"})
    assert status == 200 and steered["status"] == "running"
    assert agentruns.drain_messages(run["id"]) == ["focus on tests"]

    status, aborted = request(srv, "POST", endpoint, {"action": "abort"})
    assert status == 200 and aborted["status"] == "blocked"
    assert request(srv, "POST", endpoint, {"action": "abort"})[0] == 409
    assert request(srv, "POST", endpoint, {
        "action": "steer", "text": "too early"})[0] == 409

    status, resumed = request(srv, "POST", endpoint, {"action": "resume"})
    assert status == 200 and resumed["status"] == "running"
    assert request(srv, "POST", endpoint, {"action": "resume"})[0] == 409


def test_remote_access_is_opt_in_and_every_remote_request_is_authenticated(
        srv, monkeypatch):
    monkeypatch.setattr(web_server.config, "load_config", lambda: {
        **config.DEFAULT_CONFIG, "web_remote_access": False})
    assert request(srv, "GET", "/", token=False, host="console.example")[0] == 403

    monkeypatch.setattr(web_server.config, "load_config", lambda: {
        **config.DEFAULT_CONFIG, "web_remote_access": True})
    assert request(srv, "GET", "/", token=False, host="console.example")[0] == 403
    assert request(srv, "GET", "/", token=True, host="console.example")[0] == 200
