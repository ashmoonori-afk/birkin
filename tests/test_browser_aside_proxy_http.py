from __future__ import annotations

import base64
import socket
from http.server import BaseHTTPRequestHandler
from threading import Event
from typing import ClassVar, final
from urllib.parse import urlsplit

import pytest
from typing_extensions import override

from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.browser_aside_proxy import BrowserFilteringProxy
from birkin.browser_aside_proxy_http import read_request_header
from birkin.sandbox import NetworkPolicy, SandboxPolicy
from tests import native_browser_aside_support as support


@final
class BodyHandler(BaseHTTPRequestHandler):
    received: ClassVar[bytes] = b""
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        type(self).received = self.rfile.read(length)
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    @override
    def log_message(self, format: str, *args: object) -> None:
        del format, args


def test_proxy_relays_request_body_arriving_after_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"body-arrived-after-proxy-header-parse"
    header_parsed = Event()
    def tracked_header(
        client: socket.socket,
        wakeup: socket.socket | None = None,
    ) -> tuple[bytes, bytes]:
        result = read_request_header(client, wakeup)
        header_parsed.set()
        return result

    monkeypatch.setattr(
        "birkin.browser_aside_proxy.read_request_header",
        tracked_header,
    )
    BodyHandler.received = b""
    with support.serve(BodyHandler) as (fixture, target):
        policy = BrowserEgressPolicy(
            policy=SandboxPolicy(
                network=NetworkPolicy.ALLOWLIST,
                network_allowlist=("127.0.0.1",),
            ),
            private_network=(
                ("127.0.0.1", "127.0.0.1/32", fixture.server_port),
            ),
        )
        proxy = BrowserFilteringProxy(policy)
        proxy.start()
        parsed = urlsplit(proxy.url)
        assert parsed.hostname is not None
        assert parsed.port is not None
        username, password = proxy.credentials
        authorization = base64.b64encode(
            f"{username}:{password}".encode()
        ).decode()
        client = socket.create_connection(
            (parsed.hostname, parsed.port),
            timeout=5,
        )
        try:
            client.sendall(
                f"POST {target} HTTP/1.1\r\n".encode()
                + b"Host: 127.0.0.1\r\n"
                + f"Content-Length: {len(body)}\r\n".encode()
                + f"Proxy-Authorization: Basic {authorization}\r\n".encode()
                + b"Connection: close\r\n\r\n"
            )
            assert header_parsed.wait(timeout=5)
            client.sendall(body)
            client.shutdown(socket.SHUT_WR)
            response = client.recv(65_536)
        finally:
            client.close()
            proxy.close()

    assert response.startswith(b"HTTP/1.1 204")
    assert BodyHandler.received == body


def test_proxy_shutdown_interrupts_idle_accepted_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reading = Event()

    def tracked_header(
        client: socket.socket,
        wakeup: socket.socket | None = None,
    ) -> tuple[bytes, bytes]:
        reading.set()
        return read_request_header(client, wakeup)

    monkeypatch.setattr(
        "birkin.browser_aside_proxy.read_request_header",
        tracked_header,
    )
    proxy = BrowserFilteringProxy(BrowserEgressPolicy())
    proxy.start()
    parsed = urlsplit(proxy.url)
    assert parsed.hostname is not None
    assert parsed.port is not None
    client = socket.create_connection(
        (parsed.hostname, parsed.port),
        timeout=5,
    )
    try:
        assert reading.wait(timeout=5)
        proxy.close()
    finally:
        client.close()
