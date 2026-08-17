"""Offline tests for the gateway control plane and the local-HTTP channel."""

from __future__ import annotations

import http.client
import json
import threading
import types

import pytest

from birkin.gateway import core as gw_core
from birkin.gateway.channels import build_channels, local_http
from birkin.gateway.channels.local_http import LocalHTTPChannel
from birkin.gateway.channels.telegram import verify_token
from tests.local_http_support import local_http_timeout

# ---------------- Gateway.handle ----------------

def _fake_session(reply_prefix="echo:"):
    """A minimal Session-like object the Gateway can drive."""
    agent = types.SimpleNamespace(messages=[])

    def ask(text, on_text=None, **_kwargs):
        agent.messages.append({"role": "user", "content": [
            {"type": "text", "text": text}]})
        return f"{reply_prefix}{text}"

    return types.SimpleNamespace(
        cfg={}, agent=agent, ask=ask,
        _record_turn=lambda *_args, **_kwargs: None)


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
    g.cfg["channels"] = {"telegram": {"allowed_chat_ids": ["abc"]}}
    telegram_reply = g.handle("telegram", "abc", "hi there")
    assert telegram_reply.startswith("echo:<gateway-execution-policy>")
    assert telegram_reply.endswith("\n\nhi there")
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


def test_gateway_persistent_codex_timeout_runs_moirai_recovery(monkeypatch):
    # Given: a warm Codex session whose own timeout path reset its process.
    from birkin.codex_session import CodexTurnTimeout
    from birkin.moirai import trigger

    fake = _fake_session()
    fake._prepare_cli_turn = lambda text, **_kwargs: text
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: fake)
    gateway = gw_core.Gateway({})
    gateway._persistent = True
    assert gateway.cfg["session_goal_fallback"] is False

    class TimedOutCodex:
        def ask(self, *_args, **_kwargs):
            raise CodexTurnTimeout("silence timeout")

        def close(self):
            return None

    gateway._claude_sessions.put(("http", "u1"), TimedOutCodex())
    recovered: list[dict] = []

    def run_approved(payload, on_event=None):
        recovered.append(payload)
        if on_event is not None:
            on_event("moirai.phase", {"title": "할 일 1/2: inspect"})
        return "moirai: hard-task completed"

    monkeypatch.setattr(trigger, "run_approved", run_approved)
    progress: dict = {}

    # When: the local user sends a request through the persistent gateway.
    reply = gateway.handle("http", "u1", "continue the Kaggle work",
                           on_progress=progress.update)

    # Then: Moirai decomposes the original work and keeps progress observable.
    assert recovered == [{"script": "hard-task",
                          "task": "continue the Kaggle work"}]
    assert progress["phase"] == "할 일 1/2: inspect"
    assert reply == "moirai: hard-task completed"


def test_persistent_gateway_passes_stable_conversation_session_id(monkeypatch):
    prepared: list[str] = []
    fake = _fake_session()

    def prepare(text, **kwargs):
        prepared.append(kwargs["session_id"])
        return text

    fake._prepare_cli_turn = prepare
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: fake)
    gateway = gw_core.Gateway({})
    gateway._persistent = True

    class WarmSession:
        def ask(self, text, **_kwargs):
            return f"warm:{text}"

        def close(self):
            return None

    gateway._claude_sessions.put(("http", "user/one"), WarmSession())

    assert gateway.handle("http", "user/one", "hello") == "warm:hello"
    assert prepared == [
        gw_core.conversation_session_id("http", "user/one")
    ]
    assert "/" not in prepared[0]
    assert prepared[0] == gw_core.conversation_session_id(
        "http", "user/one"
    )
    assert prepared[0] != gw_core.conversation_session_id(
        "http", "user/two"
    )


def test_nonpersistent_gateway_passes_stable_conversation_session_id(
        monkeypatch):
    seen: list[str] = []
    fake = _fake_session()

    def ask(text, **kwargs):
        seen.append(kwargs["session_id"])
        return f"native:{text}"

    fake.ask = ask
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: fake)
    gateway = gw_core.Gateway({"gateway_persistent": False})

    assert gateway.handle("http", "user/one", "one") == "native:one"
    assert gateway.handle("http", "user/two", "two") == "native:two"
    assert gateway.handle("http", "user/one", "again") == "native:again"
    assert seen == [
        gw_core.conversation_session_id("http", "user/one"),
        gw_core.conversation_session_id("http", "user/two"),
        gw_core.conversation_session_id("http", "user/one"),
    ]


def test_conversation_session_id_uses_unambiguous_tuple_encoding():
    prefix = "a" * 25

    assert gw_core.conversation_session_id(
        prefix,
        "x\0y",
    ) != gw_core.conversation_session_id(
        f"{prefix}\0x",
        "y",
    )


def test_gateway_moirai_recovery_failure_reports_server_error(monkeypatch):
    # Given: Codex timed out and no Moirai worker route can start.
    from birkin.codex_session import CodexTurnTimeout
    from birkin.moirai import trigger

    def timed_out_ask(_text, on_text=None, **_kwargs):
        raise CodexTurnTimeout("silence timeout")

    fake = _fake_session()
    fake.ask = timed_out_ask
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: fake)
    monkeypatch.setattr(
        trigger, "run_approved",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("no Moirai route")))
    gateway = gw_core.Gateway({})

    # When: both the Codex turn and its automatic recovery route fail.
    reply = gateway.handle("http", "u1", "continue the Kaggle work")

    # Then: Birkin reports the failed recovery without the rejected timeout text.
    assert reply == gw_core.TURN_MOIRAI_RECOVERY_ERROR_REPLY
    assert "다시" not in reply
    assert gw_core.TURN_ERROR_REPLY not in reply


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
         timeout=None):
    conn = http.client.HTTPConnection(
        "127.0.0.1", channel.port,
        timeout=local_http_timeout() if timeout is None else timeout)
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


def test_local_http_stop_unblocks_a_waiting_listener():
    fake_gw = types.SimpleNamespace(
        handle=lambda *_args: "",
        pending_hard_restart=False,
    )
    channel, thread = _start_http_channel(fake_gw)
    channel.stop()
    thread.join(timeout=2.0)
    assert not thread.is_alive()


def test_local_http_message_routes_to_gateway(http_channel):
    body = json.dumps({"session": "u1", "text": "hello"}).encode()
    code, payload = _req(http_channel, "POST", "/message", body=body)
    assert code == 200
    assert json.loads(payload)["reply"] == "[http:u1] hello"


def test_local_http_timeout_runs_real_moirai_hard_task(
        monkeypatch, tmp_path):
    from birkin.codex_session import CodexTurnTimeout
    from birkin.moirai import bindings, engine

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    fake = _fake_session()
    fake.ask = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        CodexTurnTimeout("silence timeout"))
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: fake)

    roles: list[str] = []

    def spawn(_prompt, binding, _opts, _cfg, *, timeout):
        roles.append(binding.role)
        if binding.role == "planner":
            return json.dumps({"items": ["인증 기능 구현"]})
        if binding.role == "decomposer":
            return json.dumps({"items": [
                "토큰 파서를 구현 — 단위 테스트로 검증",
                "로그인 경로를 실행 — HTTP 응답으로 검증",
            ]})
        return json.dumps({"result": "완료", "followups": []})

    real_run_script = engine.run_script

    def run_script(script, **kwargs):
        binding_map = {
            role: bindings.Binding(
                role=role,
                provider=("codex" if role == "worker" else "claude"),
                model=("gpt-5.6-sol" if role == "worker" else "haiku"),
                source="meta",
            )
            for role in script.roles
        }
        return real_run_script(
            script,
            cfg={"moirai_max_agents": 8},
            bindings_map=binding_map,
            spawn=spawn,
            **kwargs,
        )

    monkeypatch.setattr(engine, "run_script", run_script)
    channel, thread = _start_http_channel(gw_core.Gateway({}))
    try:
        body = json.dumps({
            "session": "timeout-e2e",
            "text": "continue the Kaggle work",
        }).encode()
        code, payload = _req(channel, "POST", "/message", body=body)
    finally:
        channel.stop()
        thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert code == 200
    assert json.loads(payload)["reply"].startswith(
        "moirai: hard-task completed")
    assert roles == ["planner", "decomposer", "worker", "worker"]


def test_local_http_forged_host_403(http_channel):
    body = json.dumps({"text": "x"}).encode()
    code, _ = _req(http_channel, "POST", "/message", host="evil.example", body=body)
    assert code == 403


def test_local_http_remote_peer_cannot_forge_loopback_host(monkeypatch):
    real_server = local_http.ThreadingHTTPServer

    class ForcedRemoteServer(real_server):
        def get_request(self):
            request, address = super().get_request()
            return request, ("198.51.100.23", address[1])

    monkeypatch.setattr(local_http, "ThreadingHTTPServer", ForcedRemoteServer)
    calls = []
    gateway = types.SimpleNamespace(
        handle=lambda *args: calls.append(args) or "unexpected",
        pending_hard_restart=False,
    )
    channel, thread = _start_http_channel(gateway)
    try:
        body = json.dumps({"text": "x"}).encode()
        code, _ = _req(channel, "POST", "/message", body=body)
    finally:
        channel.stop()
        thread.join(timeout=2.0)

    assert code == 403
    assert calls == []


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

def test_open_telegram_without_allowlist_is_capability_stripped(
        capsys, monkeypatch):
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

    # Then: the channel starts in the public capability-stripped mode.
    assert [channel.name for channel in channels] == ["telegram"]
    output = capsys.readouterr().out
    assert "allowed_chat_ids" in output
    assert "capability-stripped" in output.lower()


def test_verify_token_empty_returns_false():
    ok, info = verify_token("")
    assert ok is False and "empty" in info
