"""Offline tests for the dashboard HTTP server (no key, no real session)."""

from __future__ import annotations

import http.client
import json
import socket
import threading
from http.server import HTTPServer

import pytest

import birkin
from birkin import approvals, store
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


def test_embedded_server_falls_back_without_clobbering_discovery() -> None:
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    occupied_port = int(blocker.getsockname()[1])
    discovery = web_server.config.birkin_home() / "web_session.json"
    discovery.parent.mkdir(parents=True, exist_ok=True)
    sentinel = {"port": 43210, "token": "standalone"}
    store._write_json(discovery, sentinel)

    background = web_server.start_background(occupied_port)
    try:
        assert int(background.httpd.server_address[1]) != occupied_port
        assert store._read_json(discovery, {}) == sentinel
    finally:
        background.close()
        blocker.close()

    assert store._read_json(discovery, {}) == sentinel


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


def test_root_does_not_issue_capability(srv):
    port, token = srv
    code, headers, body = _request("127.0.0.1", port, "GET", "/")
    assert code == 200
    text = body.decode("utf-8", "replace")
    assert "<!DOCTYPE html>" in text
    assert token not in text
    assert "Set-Cookie" not in headers


def test_secret_bootstrap_issues_httponly_capability(srv):
    port, token = srv
    code, headers, _ = _request(
        "127.0.0.1", port, "GET", f"/_bootstrap/{token}")
    assert code == 303
    assert headers["Location"] == "/"
    cookie = headers["Set-Cookie"]
    assert cookie.startswith("birkin_capability=")
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie


def test_approval_reads_require_capability_cookie(srv):
    port, token = srv
    store.add_pending(
        category="cron",
        title="sensitive action",
        description="secret payload",
        payload={"value": "do not disclose"},
    )

    code, _, body = _request(
        "127.0.0.1", port, "GET", "/api/approvals")
    assert code == 403
    assert b"sensitive action" not in body

    code, _, body = _request(
        "127.0.0.1",
        port,
        "GET",
        "/api/approvals",
        headers={"Cookie": f"birkin_capability={token}"},
    )
    assert code == 200
    assert b"sensitive action" in body


def test_api_status_payload_shape(srv):
    port, _ = srv
    code, _, body = _request("127.0.0.1", port, "GET", "/api/status")
    assert code == 200
    obj = json.loads(body)
    for key in ("model", "provider", "vault", "skills_count", "auto_approve",
                "daemon", "next_nightly", "pending_count"):
        assert key in obj


def test_api_status_reports_runtime_version(srv):
    port, _ = srv
    code, _, body = _request("127.0.0.1", port, "GET", "/api/status")

    assert code == 200
    assert json.loads(body)["version"] == birkin.__version__


def test_handler_server_version_uses_runtime_version():
    assert web_server.Handler.server_version == f"birkin-dashboard/{birkin.__version__}"


def test_run_prints_secret_bootstrap_url_for_no_browser(monkeypatch, capsys):
    class StoppingServer:
        def __init__(self, address, handler):
            self.server_address = address

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    monkeypatch.setattr(web_server, "HTTPServer", StoppingServer)

    assert web_server.run(port=8765, open_browser=False) == 0

    output = capsys.readouterr().out
    assert f"http://127.0.0.1:8765/_bootstrap/{web_server._TOKEN}" in output


def test_api_status_marks_skill_discovery_unavailable(srv, monkeypatch):
    def fail(_cfg):
        raise OSError("private discovery detail")

    monkeypatch.setattr(web_server, "build_manager", fail)
    port, _ = srv
    code, _, body = _request("127.0.0.1", port, "GET", "/api/status")
    payload = json.loads(body)

    assert code == 200
    assert payload["skills_count"] is None
    assert payload["skills_error"] == "unavailable"
    assert b"private discovery detail" not in body


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


def test_structured_action_web_contract(srv):
    port, token = srv
    action = approvals.request_answers(
        title="Deploy release",
        description="Choose the deployment target.",
        questions=[{
            "id": "target",
            "text": "Where should Birkin deploy?",
            "options": [
                {"value": "staging", "label": "Staging"},
                {"value": "production", "label": "Production"},
            ],
            "recommended": "staging",
        }],
        origin="test",
    )

    code, _, payload = _request(
        "127.0.0.1",
        port,
        "GET",
        "/api/approvals",
        headers={"Cookie": f"birkin_capability={token}"},
    )
    assert code == 200
    records = json.loads(payload)
    record = next(item for item in records if item["id"] == action["id"])
    assert record["action_state"] == "action_needed"
    assert record["questions"][0]["recommended"] == "staging"

    headers = {
        "X-Birkin-Token": token,
        "Content-Type": "application/json",
    }
    answer_body = json.dumps({
        "id": action["id"],
        "action": "answer",
        "answers": {"target": "staging"},
        "source": "web:test-user",
    }).encode()
    code, _, payload = _request(
        "127.0.0.1", port, "POST", "/api/approvals",
        headers=headers, body=answer_body)
    assert code == 200
    resolved = json.loads(payload)
    assert resolved["event"] == "action_resolved"
    assert resolved["resolved_by"] == "web:dashboard"

    code, _, payload = _request(
        "127.0.0.1", port, "POST", "/api/approvals",
        headers=headers, body=answer_body)
    assert code == 409
    assert json.loads(payload)["event"] == "reply_rejected"


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


@pytest.mark.parametrize("body", [b"[]", b'"text"', b"null"])
def test_post_approvals_requires_json_object(srv, body):
    port, token = srv
    code, _, payload = _request(
        "127.0.0.1",
        port,
        "POST",
        "/api/approvals",
        headers={"X-Birkin-Token": token, "Content-Type": "application/json"},
        body=body,
    )

    assert code == 400
    assert json.loads(payload) == {"error": "expected JSON object"}


@pytest.mark.parametrize("approval_id", ["ABCDEF123456", "../etc/passwd", "abc123", "a" * 13])
def test_post_approvals_rejects_invalid_id(srv, approval_id):
    port, token = srv
    code, _, payload = _request(
        "127.0.0.1",
        port,
        "POST",
        "/api/approvals",
        headers={"X-Birkin-Token": token, "Content-Type": "application/json"},
        body=json.dumps({"id": approval_id, "action": "reject"}).encode(),
    )

    assert code == 400
    assert json.loads(payload) == {"error": "invalid approval id"}


def test_post_rejects_untrusted_request_without_reading_body(srv, monkeypatch):
    reads = 0

    def fail_if_called(_handler):
        nonlocal reads
        reads += 1
        raise AssertionError("body read before request authentication")

    monkeypatch.setattr(web_server.Handler, "_read_body", fail_if_called)
    port, token = srv
    cases = [
        ("evil.example", "/api/approvals", token, b"403 "),
        ("127.0.0.1", "/api/approvals", "", b"403 "),
        ("127.0.0.1", "/api/nope", token, b"404 "),
    ]
    for host, path, request_token, expected in cases:
        request = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"X-Birkin-Token: {request_token}\r\n"
            "Content-Length: 65536\r\n\r\n"
        ).encode()
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            client.sendall(request)
            response = b""
            while chunk := client.recv(4096):
                response += chunk
        assert expected in response.split(b"\r\n", 1)[0]
    assert reads == 0


def test_post_approvals_body_timeout_returns_408(srv, monkeypatch):
    monkeypatch.setattr(web_server, "POST_BODY_TIMEOUT_SECONDS", 0.05)
    port, token = srv
    request = (
        "POST /api/approvals HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        f"X-Birkin-Token: {token}\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: 2\r\n\r\n"
    ).encode()

    with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
        client.sendall(request)
        response = b""
        while chunk := client.recv(4096):
            response += chunk

    assert b"408 " in response.split(b"\r\n", 1)[0]
    assert json.loads(response.split(b"\r\n\r\n", 1)[1]) == {
        "error": "request body timeout"
    }


@pytest.mark.parametrize(
    ("content_length", "expected"),
    [(None, b"400 "), ("bad", b"400 "), ("-1", b"400 "), ("65537", b"413 ")],
)
def test_post_approvals_rejects_unsafe_content_lengths(srv, content_length, expected):
    port, token = srv
    headers = [
        "POST /api/approvals HTTP/1.1",
        "Host: 127.0.0.1",
        f"X-Birkin-Token: {token}",
        "Content-Type: application/json",
    ]
    if content_length is not None:
        headers.append(f"Content-Length: {content_length}")
    request = ("\r\n".join(headers) + "\r\n\r\n").encode()

    with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
        client.sendall(request)
        client.shutdown(socket.SHUT_WR)
        response = b""
        while chunk := client.recv(4096):
            response += chunk

    assert expected in response.split(b"\r\n", 1)[0]
    assert f"Server: birkin-dashboard/{birkin.__version__}".encode() in response
