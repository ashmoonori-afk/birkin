from __future__ import annotations

import base64
import socket
from http.server import BaseHTTPRequestHandler
from typing import ClassVar, final
from urllib.parse import urlsplit

from typing_extensions import override

from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.browser_aside_proxy import BrowserFilteringProxy
from birkin.sandbox import NetworkPolicy, SandboxPolicy
from tests import native_browser_aside_support as support


@final
class UpgradeRecordingHandler(BaseHTTPRequestHandler):
    upgrades: ClassVar[list[str | None]] = []
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        type(self).upgrades.append(self.headers.get("Upgrade"))
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    @override
    def log_message(self, format: str, *args: object) -> None:
        del format, args


def test_proxy_refuses_bare_lf_smuggled_upgrade_header() -> None:
    """A bare LF must not smuggle headers past the proxy filters."""
    UpgradeRecordingHandler.upgrades = []
    with support.serve(UpgradeRecordingHandler) as (fixture, target):
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
                f"GET {target}/ HTTP/1.1\r\n".encode()
                + b"Host: 127.0.0.1\r\n"
                + f"Proxy-Authorization: Basic {authorization}\r\n".encode()
                + b"X-Pad: 1\nUpgrade: websocket\nConnection: Upgrade\r\n"
                + b"\r\n"
            )
            response = client.recv(65_536)
        finally:
            client.close()
            proxy.close()

    assert response.startswith(b"HTTP/1.1 403 Forbidden")
    assert UpgradeRecordingHandler.upgrades == []
