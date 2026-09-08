from __future__ import annotations

import asyncio
import json
import select
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import httpx

from birkin import codex_oauth, http_transport, providers
from birkin.llm import LLMClient, LLMError


class Server(ThreadingHTTPServer):
    daemon_threads = False
    allow_reuse_address = True

    def __init__(self, mode: str, body: bytes = b""):
        super().__init__(("127.0.0.1", 0), Handler)
        self.mode = mode
        self.body = body
        self.requests = 0
        self.request_seen = threading.Event()
        self.body_started = threading.Event()
        self.peer_closed = threading.Event()
        self.handler_done = threading.Event()
        self.redirect_status = 307
        self.redirect_location = "/final"
        self.authorization_headers: list[str] = []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_POST(self):
        server: Server = self.server  # type: ignore[assignment]
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        server.requests += 1
        server.authorization_headers.append(self.headers.get("Authorization", ""))
        server.request_seen.set()
        try:
            if server.mode == "redirect" and self.path != "/final":
                self.send_response(server.redirect_status)
                self.send_header("Location", server.redirect_location)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if server.mode == "unresolved_redirect":
                self.send_response(307)
                self.send_header("Content-Length", str(len(server.body)))
                self.end_headers()
                self.wfile.write(server.body)
                return
            if server.mode == "retry":
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if server.mode != "header":
                self.send_response(400 if server.mode == "error_body" else 200)
                self.send_header("Content-Type", "text/event-stream")
                length = len(server.body) if server.mode in {
                    "complete", "error_body", "redirect",
                } \
                    else len(server.body) + 1_000_000
                self.send_header("Content-Length", str(length))
                self.end_headers()
                self.wfile.write(server.body)
                self.wfile.flush()
                server.body_started.set()
                if server.mode in {"complete", "error_body"}:
                    return
                if server.mode == "body_error":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
            if peer_closed(self.connection, 2.0):
                server.peer_closed.set()
        finally:
            server.handler_done.set()

    def do_GET(self):
        self.do_POST()


def peer_closed(conn: socket.socket, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        readable, _, _ = select.select([conn], [], [], 0.05)
        if not readable:
            continue
        try:
            return conn.recv(1, socket.MSG_PEEK) == b""
        except (ConnectionError, OSError):
            return True
    return False


@pytest.fixture
def server_threads():
    active: list[tuple[Server, threading.Thread]] = []

    def start(mode: str, body: bytes = b"") -> Server:
        server = Server(mode, body)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        active.append((server, thread))
        return server

    yield start
    for server, thread in active:
        server.shutdown()
        server.server_close()
        thread.join(2)
        assert not thread.is_alive()


def run_and_cancel(target, ready: threading.Event) -> tuple[object, float]:
    result: list[object] = []
    worker = threading.Thread(target=lambda: result.append(target()))
    worker.start()
    assert ready.wait(5)
    started = time.monotonic()
    target.abort.set()
    worker.join(2)
    elapsed = time.monotonic() - started
    assert not worker.is_alive()
    return result[0], elapsed


@pytest.mark.parametrize(("provider", "factory"), [
    ("api", "api_completer"),
    ("nvidia", "http_api_completer"),
    ("codex", "codex_oauth_completer"),
])
def test_get_completer_wires_abort_to_every_http_provider(
        monkeypatch, provider, factory):
    abort = threading.Event()
    captured: list[object] = []

    def fake(*args, abort=None, **kwargs):
        captured.append(abort)
        return lambda prompt: "ok"

    monkeypatch.setattr(providers, factory, fake)
    monkeypatch.setattr(providers, "codex_oauth_available", lambda: True)

    assert providers.get_completer(provider, cfg={}, abort=abort)("prompt") == "ok"
    assert captured == [abort]


def test_openai_header_wait_cancel_closes_worker_and_socket(server_threads):
    server = server_threads("header")
    abort = threading.Event()
    client = LLMClient(
        provider="openai", model="m", api_key="k",
        base_url=f"http://127.0.0.1:{server.server_port}")

    def call():
        return client.complete(system="", messages=[], tools=[], abort=abort)

    call.abort = abort
    result, elapsed = run_and_cancel(call, server.request_seen)

    assert result["stop_reason"] == "aborted" and elapsed < 2
    assert server.peer_closed.wait(2) and server.handler_done.wait(2)


def test_codex_oauth_blocked_body_cancel_closes_worker_and_socket(
        server_threads, monkeypatch):
    server = server_threads("body", b'data: {"type":"response.output_text.delta"}\n\n')
    abort = threading.Event()
    monkeypatch.setattr(codex_oauth, "resolve_token", lambda *, abort=None: "token")
    monkeypatch.setattr(codex_oauth, "auth_headers", lambda token: {})
    monkeypatch.setattr(codex_oauth, "base_url",
                        lambda: f"http://127.0.0.1:{server.server_port}")
    complete = providers.codex_oauth_completer(abort=abort)

    def call():
        return complete("prompt")

    call.abort = abort

    result, elapsed = run_and_cancel(call, server.body_started)

    assert result == "[provider-error] codex oauth: cancelled" and elapsed < 2
    assert server.peer_closed.wait(2) and server.handler_done.wait(2)


def test_backoff_cancel_does_not_retry(server_threads):
    server = server_threads("retry")
    abort = threading.Event()
    retrying = threading.Event()
    client = LLMClient(
        provider="openai", model="m", api_key="k",
        base_url=f"http://127.0.0.1:{server.server_port}")
    client._status = lambda status: retrying.set() \
        if status.kind == "retrying" else None

    def call():
        return client.complete(system="", messages=[], tools=[], abort=abort)

    call.abort = abort
    result, elapsed = run_and_cancel(call, retrying)

    assert result["stop_reason"] == "aborted" and elapsed < 0.5
    assert server.requests == 1


def test_refresh_body_cancel_preserves_credential_bytes(
        tmp_path, server_threads, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    codex_oauth.write_store({"access_token": "expired", "refresh_token": "secret"})
    before = codex_oauth.store_path().read_bytes()
    server = server_threads("body", b'{"access_token":"partial')
    monkeypatch.setattr(codex_oauth, "_TOKEN_URL",
                        f"http://127.0.0.1:{server.server_port}/token")
    abort = threading.Event()
    errors: list[BaseException] = []

    def call():
        try:
            codex_oauth.resolve_token(abort=abort)
        except BaseException as exc:
            errors.append(exc)

    call.abort = abort
    _result, elapsed = run_and_cancel(call, server.body_started)

    assert errors and errors[0].__class__.__name__ == "HTTPAborted" and elapsed < 2
    assert codex_oauth.store_path().read_bytes() == before
    assert server.peer_closed.wait(2) and server.handler_done.wait(2)


def test_normal_openai_sse_preserves_live_text_and_tool_json(server_threads):
    events = [
        {"choices": [{"delta": {"content": "hello"}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1",
          "function": {"name": "echo", "arguments": '{"x":1}'}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]
    body = b"".join(
        f"data: {json.dumps(event)}\n\n".encode() for event in events) + b"data: [DONE]\n\n"
    server = server_threads("complete", body)
    abort = threading.Event()
    chunks: list[str] = []
    client = LLMClient(
        provider="openai", model="m", api_key="k",
        base_url=f"http://127.0.0.1:{server.server_port}")

    result = client.complete(
        system="", messages=[], tools=[], on_text=chunks.append, abort=abort)

    assert chunks == ["hello"]
    assert result["content"] == [
        {"type": "text", "text": "hello"},
        {"type": "tool_use", "id": "c1", "name": "echo", "input": {"x": 1}},
    ]
    assert result["stop_reason"] == "tool_use"


def test_normal_anthropic_sse_preserves_live_text_and_tool_json(server_threads):
    events = [
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "hello"}},
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "tool_use", "id": "c1", "name": "echo"}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "input_json_delta", "partial_json": '{"x":1}'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    ]
    body = b"".join(
        f"data: {json.dumps(event)}\n\n".encode() for event in events)
    server = server_threads("complete", body)
    abort = threading.Event()
    chunks: list[str] = []
    client = LLMClient(
        provider="anthropic", model="m", api_key="k",
        base_url=f"http://127.0.0.1:{server.server_port}")

    result = client.complete(
        system="", messages=[], tools=[], on_text=chunks.append, abort=abort)

    assert chunks == ["hello"]
    assert result["content"] == [
        {"type": "text", "text": "hello"},
        {"type": "tool_use", "id": "c1", "name": "echo", "input": {"x": 1}},
    ]
    assert result["stop_reason"] == "tool_use"


def test_error_body_never_streams_as_model_text(server_threads):
    marker = "PRIVATE PROMPT"
    body = f'data: {{"choices":[{{"delta":{{"content":"{marker}"}}}}]}}\n\n'.encode()
    server = server_threads("error_body", body)
    abort = threading.Event()
    chunks: list[str] = []
    client = LLMClient(
        provider="openai", model="m", api_key="k",
        base_url=f"http://127.0.0.1:{server.server_port}")

    with pytest.raises(LLMError) as caught:
        client.complete(
            system="", messages=[], tools=[], on_text=chunks.append, abort=abort)

    assert chunks == [] and marker not in str(caught.value)
    assert server.requests == 1


def test_partial_body_failure_is_not_reposted_or_replayed(server_threads):
    body = b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
    server = server_threads("body_error", body)
    abort = threading.Event()
    chunks: list[str] = []
    client = LLMClient(
        provider="openai", model="m", api_key="k",
        base_url=f"http://127.0.0.1:{server.server_port}")

    with pytest.raises(LLMError):
        client.complete(
            system="", messages=[], tools=[], on_text=chunks.append, abort=abort)

    assert server.requests == 1
    assert chunks == ["partial"]


def test_refresh_error_body_does_not_expose_token_or_prompt(
        tmp_path, server_threads, monkeypatch):
    marker = "PRIVATE TOKEN AND PROMPT"
    server = server_threads(
        "error_body", json.dumps({"error": {"message": marker}}).encode())
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    codex_oauth.write_store({"access_token": "expired", "refresh_token": marker})
    monkeypatch.setattr(codex_oauth, "_TOKEN_URL",
                        f"http://127.0.0.1:{server.server_port}/token")

    result = providers.codex_oauth_completer(abort=threading.Event())("prompt")

    assert result.startswith("[provider-error] codex oauth:")
    assert marker not in result
    assert server.requests == 1


def test_sync_transport_called_inside_running_loop_joins_its_worker(server_threads):
    server = server_threads("complete", b'{"choices":[]}')
    abort = threading.Event()
    client = LLMClient(
        provider="openai", model="m", api_key="k",
        base_url=f"http://127.0.0.1:{server.server_port}")

    async def call():
        with pytest.raises(LLMError, match="no choices"):
            client.complete(system="", messages=[], tools=[], abort=abort)

    asyncio.run(call())
    assert server.handler_done.wait(2)


def test_openai_200_error_json_does_not_leak_reflected_body(server_threads):
    marker = "PRIVATE TOKEN AND PROMPT"
    server = server_threads(
        "complete", json.dumps({"error": {"message": marker}}).encode())
    client = LLMClient(
        provider="openai", model="m", api_key="k",
        base_url=f"http://127.0.0.1:{server.server_port}")

    with pytest.raises(LLMError) as caught:
        client.complete(
            system="", messages=[], tools=[], abort=threading.Event())

    assert "no choices" in str(caught.value)
    assert marker not in str(caught.value)


def test_abort_wins_over_simultaneous_transport_error(monkeypatch):
    abort = threading.Event()

    class Stream:
        async def __aenter__(self):
            abort.set()
            await asyncio.sleep(0)
            raise httpx.ConnectError("safe synthetic error")

        async def __aexit__(self, *_args):
            return False

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def stream(self, *_args, **_kwargs):
            return Stream()

    monkeypatch.setattr(http_transport.httpx, "AsyncClient", Client)

    with pytest.raises(http_transport.HTTPAborted):
        http_transport.post(
            "https://example.invalid", headers={}, data=b"", timeout=1,
            abort=abort,
        )


def test_cancellable_transport_does_not_repost_redirect(server_threads):
    body = json.dumps({
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
    }).encode()
    server = server_threads("redirect", body)
    client = LLMClient(
        provider="openai", model="m", api_key="k",
        base_url=f"http://127.0.0.1:{server.server_port}")

    with pytest.raises(LLMError) as caught:
        client.complete(
            system="", messages=[], tools=[], abort=threading.Event())

    assert caught.value.status == 307
    assert server.requests == 1


@pytest.mark.parametrize("status", [302, 303, 307, 308])
def test_legacy_transport_does_not_follow_redirect_with_bearer(
    server_threads, status,
):
    target = server_threads("complete", b"target")
    source = server_threads("redirect")
    source.redirect_status = status
    source.redirect_location = f"http://127.0.0.1:{target.server_port}/capture"
    client = LLMClient(
        provider="openai", model="m", api_key="fakeBearer", base_url="",
    )

    with pytest.raises(LLMError) as caught:
        client._post(
            f"http://127.0.0.1:{source.server_port}/start",
            {"Authorization": "Bearer fakeBearer"}, {}, stream=False,
        )

    assert caught.value.status == status
    assert source.requests == 1
    assert source.authorization_headers == ["Bearer fakeBearer"]
    assert target.requests == 0


def test_no_redirect_helper_preserves_response_contract(server_threads):
    server = server_threads("complete", b"response body")
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_port}/body",
        data=b"request", method="POST",
    )

    with http_transport.open_no_redirect(request, timeout=2) as response:
        assert response.status == 200
        assert response.read() == b"response body"


def test_codex_oauth_provider_does_not_follow_redirect_with_bearer(
    server_threads, monkeypatch,
):
    target = server_threads("complete", b"target")
    source = server_threads("redirect")
    source.redirect_status = 302
    source.redirect_location = f"http://127.0.0.1:{target.server_port}/capture"
    monkeypatch.setattr(codex_oauth, "resolve_token", lambda: "fakeBearer")
    monkeypatch.setattr(
        codex_oauth, "base_url",
        lambda: f"http://127.0.0.1:{source.server_port}",
    )

    result = providers.codex_oauth_completer()("safe")

    assert result.startswith("[provider-error] codex oauth HTTP 302")
    assert "fakeBearer" not in result
    assert source.requests == 1
    assert target.requests == 0


@pytest.mark.parametrize("url", [
    "file:///tmp/x", "ftp://example.org/x", "https://user@example.org/x",
    "https:///missing-host",
])
def test_no_redirect_helper_rejects_unsupported_urls(url):
    with pytest.raises(urllib.error.URLError, match="unsupported request URL"):
        http_transport.open_no_redirect(urllib.request.Request(url), timeout=2)


def test_unresolved_redirect_is_not_parsed_as_success(server_threads):
    marker = "PRIVATE REDIRECT BODY"
    server = server_threads("unresolved_redirect", marker.encode())
    chunks: list[str] = []
    client = LLMClient(
        provider="openai", model="m", api_key="k",
        base_url=f"http://127.0.0.1:{server.server_port}")

    with pytest.raises(LLMError) as caught:
        client.complete(
            system="", messages=[], tools=[], on_text=chunks.append,
            abort=threading.Event(),
        )

    assert caught.value.status == 307
    assert marker not in str(caught.value)
    assert chunks == []


@pytest.mark.parametrize("terminal_type", ["response.failed", "response.incomplete"])
def test_responses_terminal_failure_rejects_partial_text(terminal_type):
    marker = "PRIVATE TOKEN AND PROMPT"
    raw = "\n\n".join([
        'data: {"type":"response.output_text.delta","delta":"partial"}',
        "data: " + json.dumps({
            "type": terminal_type,
            "response": {"error": {"message": marker}},
        }),
    ])

    result = providers._responses_text(raw)

    assert result.startswith("[provider-error]")
    assert "partial" not in result
    assert marker not in result


def test_openai_stream_error_rejects_partial_text_without_leaking_detail():
    marker = "PRIVATE TOKEN AND PROMPT"
    frames = [
        b'data: {"choices":[{"delta":{"content":"partial"}}]}',
        ("data: " + json.dumps({"error": {"message": marker}})).encode(),
    ]
    chunks: list[str] = []

    with pytest.raises(LLMError) as caught:
        LLMClient._read_openai_stream(frames, chunks.append)

    assert chunks == ["partial"]
    assert marker not in str(caught.value)


def test_anthropic_stream_error_keeps_kind_without_leaking_detail():
    marker = "PRIVATE maximum context length TOKEN AND PROMPT"
    frames = [
        b'data: {"type":"content_block_start","index":0,'
        b'"content_block":{"type":"text"}}',
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":"partial"}}',
        ("data: " + json.dumps({
            "type": "error", "error": {"message": marker},
        })).encode(),
    ]
    chunks: list[str] = []

    with pytest.raises(LLMError) as caught:
        LLMClient._read_anthropic_stream(frames, chunks.append)

    assert caught.value.kind == "overflow"
    assert chunks == ["partial"]
    assert marker not in str(caught.value)
