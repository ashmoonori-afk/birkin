"""Offline tests for the dashboard HTTP server (no key, no real session)."""

from __future__ import annotations

import http.client
import json
import threading
from http.server import HTTPServer

import pytest

from birkin import store
from birkin.web import server as web_server


def _request(host_header: str, port: int, method: str, path: str,
             headers: dict | None = None, body: bytes | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    hdrs = dict(headers or {})
    hdrs.setdefault("Host", host_header)
    conn.request(method, path, body=body, headers=hdrs)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, dict(resp.getheaders()), data


@pytest.fixture
def srv():
    httpd = HTTPServer(("127.0.0.1", 0), web_server.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield port, web_server._TOKEN
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_index_serves_html_with_token_injected(srv):
    port, token = srv
    code, _, body = _request("127.0.0.1", port, "GET", "/")
    assert code == 200
    text = body.decode("utf-8", "replace")
    assert "<!DOCTYPE html>" in text
    assert "__BIRKIN_TOKEN__" not in text          # placeholder replaced
    assert f'BIRKIN_TOKEN = "{token}"' in text     # actual token present


def test_api_status_payload_shape(srv):
    port, _ = srv
    code, _, body = _request("127.0.0.1", port, "GET", "/api/status")
    assert code == 200
    obj = json.loads(body)
    for key in ("model", "provider", "vault", "skills_count", "auto_approve",
                "daemon", "next_nightly", "pending_count"):
        assert key in obj


def test_api_skills_and_runs(srv):
    port, _ = srv
    code, _, body = _request("127.0.0.1", port, "GET", "/api/skills")
    assert code == 200 and isinstance(json.loads(body), list)

    # runs starts empty, gets populated by save_run
    assert _request("127.0.0.1", port, "GET", "/api/runs")[2] == b"[]"
    store.save_run("chat", "x", usage=store.estimate_usage("p", "r"))
    code, _, body = _request("127.0.0.1", port, "GET", "/api/runs")
    runs = json.loads(body)
    assert len(runs) == 1 and runs[0]["kind"] == "chat"


def test_api_jobs_envelope(srv):
    port, _ = srv
    code, _, body = _request("127.0.0.1", port, "GET", "/api/jobs")
    assert code == 200
    obj = json.loads(body)
    assert "status" in obj and "jobs" in obj


def test_unknown_get_404(srv):
    port, _ = srv
    code, _, _ = _request("127.0.0.1", port, "GET", "/nope")
    assert code == 404


def test_post_approvals_token_and_host_gates(srv):
    port, token = srv
    rec = store.add_pending(category="cron", title="t", description="",
                            payload={"name": "x", "hour": 1, "minute": 0})
    body = json.dumps({"id": rec["id"], "action": "reject"}).encode()
    hdrs = {"Content-Type": "application/json"}

    # missing token -> 403
    code, _, _ = _request("127.0.0.1", port, "POST", "/api/approvals",
                          headers=hdrs, body=body)
    assert code == 403

    # forged Host (even with token) -> 403
    code, _, _ = _request("evil.example", port, "POST", "/api/approvals",
                          headers={**hdrs, "X-Birkin-Token": token}, body=body)
    assert code == 403

    # valid token + localhost Host -> 200
    code, _, payload = _request("127.0.0.1", port, "POST", "/api/approvals",
                                headers={**hdrs, "X-Birkin-Token": token},
                                body=body)
    assert code == 200
    assert json.loads(payload).get("ok") is True
    assert store.list_pending() == []  # resolved


def test_post_approvals_bad_path_and_json(srv):
    port, token = srv
    code, _, _ = _request("127.0.0.1", port, "POST", "/api/nope",
                          headers={"X-Birkin-Token": token,
                                   "Content-Type": "application/json"},
                          body=b"{}")
    assert code == 404
    code, _, _ = _request("127.0.0.1", port, "POST", "/api/approvals",
                          headers={"X-Birkin-Token": token,
                                   "Content-Type": "application/json"},
                          body=b"not-json")
    assert code == 400
