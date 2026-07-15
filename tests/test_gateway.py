"""Offline tests for the gateway control plane and the local-HTTP channel."""

from __future__ import annotations

import http.client
import json
import socket
import threading
import types

import pytest

from birkin.gateway import core as gw_core
from birkin.gateway.channels.local_http import LocalHTTPChannel
from birkin.gateway.channels.telegram import verify_token


# ---------------- Gateway.handle ----------------

def _fake_session(reply_prefix="echo:"):
    """A minimal Session-like object the Gateway can drive."""
    agent = types.SimpleNamespace(messages=[])

    def ask(text, on_text=None, **_kwargs):
        agent.messages.append({"role": "user", "content": [
            {"type": "text", "text": text}]})
        return f"{reply_prefix}{text}"

    return types.SimpleNamespace(cfg={}, agent=agent, ask=ask)


@pytest.fixture
def gateway(monkeypatch):
    fake = _fake_session()
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: fake)
    g = gw_core.Gateway({})
    return g, fake


def test_gateway_routes_per_chat(gateway):
    g, _ = gateway
    assert g.handle("http", "u1", "hello") == "echo:hello"
    assert g.handle("http", "u1", "again") == "echo:again"
    # different chat keeps its own history
    assert g.handle("telegram", "abc", "hi there") == "echo:hi there"
    assert len(g._chats) == 2


def test_gateway_empty_message_is_noop(gateway):
    g, _ = gateway
    assert g.handle("http", "u1", "   ") == ""


def test_gateway_slash_new_resets_chat(gateway):
    g, _ = gateway
    g.handle("http", "u1", "first")
    assert g._chats[("http", "u1")]   # non-empty
    msg = g.handle("http", "u1", "/new")
    assert "new conversation" in msg.lower()
    assert g._chats[("http", "u1")] == []


def test_gateway_returns_friendly_error_not_raw(monkeypatch):
    # P1-3: the raw exception is logged server-side, but the chat gets a
    # friendly line — no path/internal leak to a Telegram user.
    def boom_ask(text, on_text=None, **_kwargs):
        raise RuntimeError("boom /secret/path")
    fake = _fake_session()
    fake.ask = boom_ask
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: fake)
    g = gw_core.Gateway({})
    out = g.handle("http", "u1", "hi")
    assert "boom" not in out and "secret" not in out
    assert "⚠️" in out


# ---------------- LocalHTTPChannel ----------------

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def http_channel():
    port = _free_port()
    ch = LocalHTTPChannel(port)
    fake_gw = types.SimpleNamespace(handle=lambda ch_name, cid, txt: f"[{ch_name}:{cid}] {txt}")
    t = threading.Thread(target=ch.start, args=(fake_gw,), daemon=True)
    t.start()

    # wait briefly for the server to bind
    import time
    for _ in range(40):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)
    yield port


def _req(port, method, path, host="127.0.0.1", body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    headers = {"Host": host}
    if body is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=body, headers=headers)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, data


def test_local_http_health(http_channel):
    code, body = _req(http_channel, "GET", "/health")
    assert code == 200
    assert json.loads(body)["ok"] is True


def test_local_http_message_routes_to_gateway(http_channel):
    body = json.dumps({"session": "u1", "text": "hello"}).encode()
    code, payload = _req(http_channel, "POST", "/message", body=body)
    assert code == 200
    assert json.loads(payload)["reply"] == "[http:u1] hello"


def test_local_http_forged_host_403(http_channel):
    body = json.dumps({"text": "x"}).encode()
    code, _ = _req(http_channel, "POST", "/message", host="evil.example", body=body)
    assert code == 403


def test_local_http_bad_paths_and_payloads(http_channel):
    code, _ = _req(http_channel, "GET", "/whatever")
    assert code == 404
    code, _ = _req(http_channel, "POST", "/elsewhere", body=b"{}")
    assert code == 404
    code, _ = _req(http_channel, "POST", "/message", body=b"not-json")
    assert code == 400
    code, _ = _req(http_channel, "POST", "/message", body=b"{}")
    assert code == 400  # empty text


# ---------------- Telegram verify_token (offline error path) ----------------

def test_verify_token_empty_returns_false():
    ok, info = verify_token("")
    assert ok is False and "empty" in info
