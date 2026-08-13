"""Hardening: streaming stability, stale approvals, fault containment.

Contracts: a tool whose result has not arrived renders as running (never as
failed) in exactly one stable line; an expired approval offers no
approve/reject affordance; a broken contract export returns 500 without
killing the server (the next request succeeds) — UI-layer failure never
takes the backend down.
"""
from __future__ import annotations

import http.client
import threading
from http.server import HTTPServer

import pytest

from birkin import uikit, uistate, workbench
from birkin.web import server as web_server


# -- streaming layout stability ---------------------------------------------

def test_inflight_tool_renders_as_running_not_failed():
    tool = {"name": "run_shell", "target": "pytest -q", "ok": None}
    line = uikit.tool_summary(tool, 80, color=False)
    assert uistate.glyph("running") in line
    assert uistate.glyph("failed") not in line


def test_streaming_tool_occupies_one_stable_line():
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "run_shell",
             "input": {"command": "sleep 100"}}]},
    ]
    first = workbench.render_session(messages, set(), 80, 24, color=False)
    again = workbench.render_session(messages, set(), 80, 24, color=False)
    assert first == again                      # identical logical state
    tool_lines = [ln for ln in first if "run_shell" in ln]
    assert len(tool_lines) == 1


# -- stale approval ----------------------------------------------------------

def test_expired_approval_offers_no_actions():
    rec = {"id": "e" * 12, "title": "만료된 승인", "category": "shell",
           "origin": "cron", "status": "pending",
           "payload": {"command": "rm -rf x"},
           "expires_at": "2020-01-01T00:00:00+00:00"}
    lines = uikit.approval_card(rec, 80, color=False)
    text = "\n".join(lines)
    assert uistate.label("expired") in text
    assert "a 승인" not in text


# -- fault containment: broken UI contract never kills the server ------------

def _request(port: int, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path, headers={"Host": "127.0.0.1"})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


@pytest.fixture
def srv():
    httpd = HTTPServer(("127.0.0.1", 0), web_server.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_contract_failure_is_500_and_server_survives(srv, monkeypatch):
    from birkin import uistate as uistate_mod

    def boom():
        raise RuntimeError("contract broken")

    monkeypatch.setattr(uistate_mod, "schema", boom)
    code, _ = _request(srv, "/api/contract")
    assert code == 500
    monkeypatch.undo()
    code, _ = _request(srv, "/api/contract")
    assert code == 200
