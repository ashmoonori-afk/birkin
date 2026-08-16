from __future__ import annotations

import base64
import socket
from typing import cast
from urllib.parse import urlsplit

import pytest

from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.browser_aside_proxy import BrowserFilteringProxy
from birkin.sandbox import NetworkPolicy, SandboxPolicy
from tests import native_browser_aside_support as support


def _request(
    proxy: BrowserFilteringProxy,
    target: str,
    *,
    authenticated: bool = True,
    upgrade: bool = False,
) -> bytes:
    parsed = urlsplit(proxy.url)
    assert parsed.hostname is not None
    assert parsed.port is not None
    with socket.create_connection(
        (parsed.hostname, parsed.port),
        timeout=5,
    ) as client:
        username, password = proxy.credentials
        authorization = (
            b"Proxy-Authorization: Basic "
            + base64.b64encode(
                f"{username}:{password}".encode()
            )
            + b"\r\n"
            if authenticated
            else b""
        )
        upgrade_headers = (
            b"Connection: Upgrade\r\n"
            + b"Upgrade: websocket\r\n"
            if upgrade
            else b"Connection: close\r\n"
        )
        client.sendall(
            f"GET {target} HTTP/1.1\r\n".encode()
            + b"Host: 127.0.0.1\r\n"
            + authorization
            + upgrade_headers
            + b"\r\n"
        )
        chunks: list[bytes] = []
        while chunk := client.recv(65_536):
            chunks.append(chunk)
    return b"".join(chunks)


def test_proxy_connects_only_to_exact_policy_vetted_peer() -> None:
    with support.serve(support.FixtureHandler) as (fixture, url):
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
        try:
            response = _request(proxy, url)
        finally:
            proxy.close()
    assert response.startswith(b"HTTP/1.1 200")
    assert support.FIXTURE_TEXT.encode() in response


def test_proxy_closes_peer_that_differs_from_pinned_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeUpstream:
        closed = False

        @staticmethod
        def getpeername() -> tuple[str, int]:
            return "127.0.0.1", 443

        def close(self) -> None:
            self.closed = True

    upstream = FakeUpstream()
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: cast(
            socket.socket,
            cast(object, upstream),
        ),
    )
    policy = BrowserEgressPolicy(
        policy=SandboxPolicy(
            network=NetworkPolicy.ALLOWLIST,
            network_allowlist=("example.com",),
        ),
        resolver=lambda _host: ("93.184.216.34",),
    )
    proxy = BrowserFilteringProxy(policy)
    proxy.start()
    try:
        with pytest.raises(BrowserAsideError) as captured:
            _ = proxy._connect("https://example.com/")
    finally:
        proxy.close()

    assert captured.value.code == "peer_mismatch_denied"
    assert upstream.closed is True


def test_proxy_refuses_unconditional_control_address() -> None:
    with support.serve(support.FixtureHandler) as (fixture, url):
        authority = f"127.0.0.1:{fixture.server_port}"
        policy = BrowserEgressPolicy(
            policy=SandboxPolicy(
                network=NetworkPolicy.ALLOWLIST,
                network_allowlist=("127.0.0.1",),
            ),
            private_network=(
                ("127.0.0.1", "127.0.0.1/32", fixture.server_port),
            ),
            control_addresses=(authority,),
        )
        proxy = BrowserFilteringProxy(policy)
        proxy.start()
        try:
            response = _request(proxy, url)
        finally:
            proxy.close()
    assert response.startswith(b"HTTP/1.1 403 Forbidden")


def test_proxy_refuses_unauthenticated_local_clients() -> None:
    policy = BrowserEgressPolicy()
    proxy = BrowserFilteringProxy(policy)
    proxy.start()
    try:
        response = _request(
            proxy,
            "https://example.com/",
            authenticated=False,
        )
    finally:
        proxy.close()
    assert response.startswith(
        b"HTTP/1.1 407 Proxy Authentication Required"
    )
    assert b"Proxy-Authenticate: Basic" in response


def test_proxy_refuses_websocket_upgrade_before_connect() -> None:
    proxy = BrowserFilteringProxy(BrowserEgressPolicy())
    proxy.start()
    try:
        response = _request(
            proxy,
            "http://example.com/socket",
            upgrade=True,
        )
    finally:
        proxy.close()
    assert response.startswith(b"HTTP/1.1 403 Forbidden")
