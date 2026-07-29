"""Offline tests for the gateway control plane and the local-HTTP channel."""

from __future__ import annotations

import http.client
import json
import threading
import types

import pytest

from birkin.gateway import core as gw_core
from birkin.gateway.channels import build_channels
from birkin.gateway.channels import local_http
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

def _start_http_channel(gateway):
    channel = LocalHTTPChannel(0)
    thread = threading.Thread(
        target=channel.start, args=(gateway,), daemon=True)
    thread.start()
    assert channel.wait_until_ready(1.0)
    return channel, thread


@pytest.fixture
def http_channel():
    fake_gw = types.SimpleNamespace(
        handle=lambda ch_name, cid, txt: f"[{ch_name}:{cid}] {txt}",
        pending_hard_restart=False)
    channel, thread = _start_http_channel(fake_gw)
    try:
        yield channel
    finally:
        channel.stop()
        thread.join(timeout=2.0)
        assert not thread.is_alive()


def _req(channel, method, path, host="127.0.0.1", body=None,
         timeout=2.0):
    conn = http.client.HTTPConnection(
        "127.0.0.1", channel.port, timeout=timeout)
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


def test_local_http_stays_responsive_during_a_blocked_turn():
    # Given: one message is held inside the gateway turn.
    entered = threading.Event()
    release = threading.Event()

    def handle(_channel, _chat_id, text):
        if text == "block":
            entered.set()
            assert release.wait(2.0)
        return text

    channel, server_thread = _start_http_channel(
        types.SimpleNamespace(
            handle=handle, pending_hard_restart=False))
    response: dict[str, tuple[int, bytes]] = {}
    error: list[Exception] = []

    def send_blocking_message():
        try:
            body = json.dumps(
                {"session": "slow", "text": "block"}).encode()
            response["message"] = _req(
                channel, "POST", "/message", body=body)
        except Exception as exc:
            error.append(exc)

    request_thread = threading.Thread(target=send_blocking_message)
    request_thread.start()
    assert entered.wait(1.0)

    # When: health is queried before the blocked turn is released.
    try:
        code, body = _req(
            channel, "GET", "/health", timeout=1.0)
    finally:
        release.set()
        request_thread.join(timeout=2.0)
        channel.stop()
        server_thread.join(timeout=2.0)

    # Then: request dispatch was concurrent and every thread stopped.
    assert code == 200
    assert json.loads(body) == {"ok": True, "channel": "http"}
    assert not error
    assert response["message"][0] == 200
    assert not request_thread.is_alive()
    assert not server_thread.is_alive()


def test_local_http_fixture_stops_server():
    # Given: a listening server with explicit lifecycle ownership.
    gateway = types.SimpleNamespace(
        handle=lambda *_args: "ok", pending_hard_restart=False)
    channel, thread = _start_http_channel(gateway)

    # When: the owner stops it.
    channel.stop()
    thread.join(timeout=2.0)

    # Then: serve_forever returned and readiness was cleared.
    assert not thread.is_alive()
    assert not channel.wait_until_ready(0)


def test_local_http_stop_does_not_deadlock_before_serve_loop(monkeypatch):
    # Given: startup has published the listener but is blocked before serving.
    print_entered = threading.Event()
    release_print = threading.Event()

    def blocking_print(*_args, **_kwargs):
        print_entered.set()
        assert release_print.wait(2.0)

    monkeypatch.setattr(
        local_http, "print", blocking_print, raising=False)
    gateway = types.SimpleNamespace(
        handle=lambda *_args: "ok", pending_hard_restart=False)
    channel = LocalHTTPChannel(0)
    server_thread = threading.Thread(
        target=channel.start, args=(gateway,), daemon=True)
    server_thread.start()
    assert print_entered.wait(1.0)

    stopped = threading.Event()

    def stop_channel():
        channel.stop()
        stopped.set()

    stop_thread = threading.Thread(target=stop_channel, daemon=True)
    stop_thread.start()

    # When/Then: stop returns without waiting for serve_forever to begin.
    try:
        assert stopped.wait(0.5)
    finally:
        release_print.set()
        stop_thread.join(timeout=2.0)
        server_thread.join(timeout=2.0)

    assert not stop_thread.is_alive()
    assert not server_thread.is_alive()
    assert not channel.wait_until_ready(0)


# ---------------- Telegram verify_token (offline error path) ----------------

def test_open_telegram_without_allowlist_is_refused(capsys, monkeypatch):
    # Given: Telegram is enabled with a token but no authorized chat ids.
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("BIRKIN_TELEGRAM_TOKEN", raising=False)
    cfg = {
        "channels": {
            "http": {"enabled": False},
            "telegram": {
                "enabled": True,
                "token": "probe-token",
                "allowed_chat_ids": [],
            },
        },
    }

    # When: the gateway constructs its enabled channels.
    channels = build_channels(cfg)

    # Then: the reachable Telegram channel is refused before it can start.
    assert channels == []
    output = capsys.readouterr().out
    assert "allowed_chat_ids" in output
    assert "refusing" in output.lower()


def test_verify_token_empty_returns_false():
    ok, info = verify_token("")
    assert ok is False and "empty" in info
