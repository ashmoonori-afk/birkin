"""Real-socket lifecycle regressions for the local HTTP channel."""

from __future__ import annotations

import http.client
import io
import threading
import types

from birkin.gateway.channels import local_http
from birkin.gateway.channels.local_http import LocalHTTPChannel
from tests.local_http_support import local_http_timeout


def test_invalid_path_404_drain_consumes_the_declared_body() -> None:
    # Given: the exact two-byte body declared by the failing invalid-path POST.
    class Connection:
        def __init__(self) -> None:
            self.timeout: float | None = None

        def gettimeout(self) -> float | None:
            return self.timeout

        def settimeout(self, timeout: float | None) -> None:
            self.timeout = timeout

    request = types.SimpleNamespace(
        connection=Connection(),
        headers={"Content-Length": "2"},
        rfile=io.BytesIO(b"{}"),
    )

    # When: the bounded invalid-path drain runs.
    local_http._drain_rejected_body(request)

    # Then: no request bytes remain to reset the 404 during connection close.
    assert request.rfile.read() == b""


def test_invalid_path_404_drains_before_sending_complete_response(monkeypatch) -> None:
    # Given: the certifier's exact GET then two-byte invalid-path POST sequence.
    drain_called = threading.Event()
    original_drain = local_http._drain_rejected_body

    def observed_drain(request) -> None:
        original_drain(request)
        drain_called.set()

    monkeypatch.setattr(local_http, "_drain_rejected_body", observed_drain)
    gateway = types.SimpleNamespace(
        handle=lambda *_args: "unexpected",
        pending_hard_restart=False,
    )
    channel = LocalHTTPChannel(0, insecure_no_token=True)
    server_thread = threading.Thread(
        target=channel.start,
        args=(gateway,),
        daemon=True,
    )
    server_thread.start()
    assert channel.wait_until_ready(1.0)

    try:
        # When: both requests run after listener readiness was subscribed.
        responses: list[tuple[int, bytes]] = []
        for method, path, body in (
            ("GET", "/whatever", None),
            ("POST", "/elsewhere", b"{}"),
        ):
            connection = http.client.HTTPConnection(
                "127.0.0.1",
                channel.port,
                timeout=local_http_timeout(),
            )
            try:
                connection.request(
                    method,
                    path,
                    body=body,
                    headers={
                        "Host": "127.0.0.1",
                        "Content-Type": "application/json",
                    },
                )
                response = connection.getresponse()
                responses.append((response.status, response.read()))
            finally:
                connection.close()

        # Then: the drain event precedes a complete 404 response.
        assert responses == [
            (404, b'{"error": "not found"}'),
            (404, b'{"error": "not found"}'),
        ]
        assert drain_called.is_set()
    finally:
        channel.stop()
        server_thread.join(timeout=2.0)

    assert not server_thread.is_alive()


def test_unauthorized_large_body_responses_are_complete() -> None:
    gateway = types.SimpleNamespace(
        handle=lambda *_args: "unexpected",
        pending_hard_restart=False,
    )
    channel = LocalHTTPChannel(0, token="correct-token")
    server_thread = threading.Thread(
        target=channel.start,
        args=(gateway,),
        daemon=True,
    )
    server_thread.start()
    assert channel.wait_until_ready(1.0)

    try:
        body = b"x" * 1_000_000
        responses: list[tuple[int, bytes]] = []
        for _ in range(32):
            connection = http.client.HTTPConnection(
                "127.0.0.1",
                channel.port,
                timeout=local_http_timeout(),
            )
            try:
                connection.request(
                    "POST",
                    "/message",
                    body=body,
                    headers={
                        "Host": "127.0.0.1",
                        "Content-Type": "application/json",
                    },
                )
                response = connection.getresponse()
                responses.append((response.status, response.read()))
            finally:
                connection.close()
    finally:
        channel.stop()
        server_thread.join(timeout=2.0)

    assert responses == [(401, b'{"error": "unauthorized"}') for _ in range(32)]
    assert not server_thread.is_alive()
