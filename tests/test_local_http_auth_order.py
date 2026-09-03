"""An unauthenticated local caller must be refused before the body is read."""

from __future__ import annotations

import socket
import threading
import types
from collections.abc import Iterator

import pytest

from birkin.gateway.channels.local_http import LocalHTTPChannel
from tests.local_http_support import local_http_timeout

_TOKEN = "correct-horse-battery-staple"


@pytest.fixture
def channel(monkeypatch: pytest.MonkeyPatch) -> Iterator[LocalHTTPChannel]:
    monkeypatch.delenv("BIRKIN_HTTP_TOKEN", raising=False)
    gateway = types.SimpleNamespace(
        handle=lambda *_args: "unexpected",
        pending_hard_restart=False,
    )
    started = LocalHTTPChannel(0, token=_TOKEN)
    thread = threading.Thread(
        target=started.start,
        args=(gateway,),
        daemon=True,
    )
    thread.start()
    assert started.wait_until_ready(local_http_timeout())
    try:
        yield started
    finally:
        started.stop()
        thread.join(timeout=local_http_timeout())


def _post_headers_only(port: int, token: str, length: int) -> bytes:
    """Announce a body of ``length`` bytes and then send none of it."""
    with socket.create_connection(
        ("127.0.0.1", port),
        timeout=local_http_timeout(),
    ) as client:
        client.sendall(
            b"POST /message HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"X-Birkin-Token: " + token.encode() + b"\r\n"
            b"Content-Length: " + str(length).encode() + b"\r\n"
            b"\r\n"
        )
        received = b""
        while b"\r\n\r\n" not in received:
            chunk = client.recv(4096)
            if not chunk:
                break
            received += chunk
        return received


def test_wrong_token_is_refused_before_the_declared_body_is_handled(
    channel: LocalHTTPChannel,
) -> None:
    # A 1 MB body that never arrives: reading it before authenticating pins
    # this handler thread for the 2s body budget and answers 408, not 401.
    response = _post_headers_only(channel.port, "wrong-token", 1_000_000)

    assert response.startswith(b"HTTP/1.0 401 ") or response.startswith(
        b"HTTP/1.1 401 "
    )
    assert b"Connection: close\r\n" in response


def test_wrong_token_never_leaks_a_body_shaped_status(
    channel: LocalHTTPChannel,
) -> None:
    # Over the 1 MB cap: an unauthenticated caller must learn nothing about
    # the body rules, so this is 401 rather than 413.
    response = _post_headers_only(channel.port, "wrong-token", 1_000_001)

    assert b" 401 " in response.split(b"\r\n", 1)[0]


def test_the_right_token_still_reaches_body_handling(
    channel: LocalHTTPChannel,
) -> None:
    # Same oversized declaration, correct token: now the body rules apply.
    response = _post_headers_only(channel.port, _TOKEN, 1_000_001)

    assert b" 413 " in response.split(b"\r\n", 1)[0]
