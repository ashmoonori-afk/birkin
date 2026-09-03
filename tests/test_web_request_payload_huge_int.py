"""An oversized integer literal must fail as a payload error, never as a dead socket."""

from __future__ import annotations

import http.client
import json
import sys
import threading
from collections.abc import Iterator
from http.server import HTTPServer

import pytest

from birkin.web import server as web_server
from birkin.web.request_payload import RequestPayloadError, parse_object
from tests.local_http_support import local_http_timeout


def _huge_int_body() -> bytes:
    return b'{"n":' + b"9" * (sys.get_int_max_str_digits() + 1) + b"}"


@pytest.fixture
def server() -> Iterator[tuple[int, str]]:
    httpd = HTTPServer(("127.0.0.1", 0), web_server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(httpd.server_address[1]), web_server.capability_token()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_huge_integer_literal_raises_a_payload_error() -> None:
    """json.loads refuses this literal with a plain ValueError, not a
    JSONDecodeError, so the parser must map it like any other bad body."""
    with pytest.raises(RequestPayloadError) as caught:
        _ = parse_object(_huge_int_body())

    assert str(caught.value) == "bad json"


def test_huge_integer_post_answers_400_instead_of_hanging_up(
    server: tuple[int, str],
) -> None:
    port, token = server
    connection = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=local_http_timeout()
    )
    try:
        connection.request(
            "POST",
            "/api/context",
            body=_huge_int_body(),
            headers={
                "Host": "127.0.0.1",
                "Content-Type": "application/json",
                "X-Birkin-Token": token,
            },
        )
        response = connection.getresponse()
        payload = response.read()
        status = response.status
    finally:
        connection.close()

    assert status == 400
    assert json.loads(payload)["error"] == "bad json"
