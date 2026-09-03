"""Deeply nested JSON must fail as a payload error, never as a dead socket."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from http.server import HTTPServer

import pytest

from birkin.web import server as web_server
from birkin.web import request_payload
from birkin.web.request_payload import RequestPayloadError, parse_object
from tests.local_http_support import local_http_timeout

_DEPTH = 600


def _nested_body(depth: int) -> bytes:
    return ('{"a":' * depth + "1" + "}" * depth).encode("utf-8")


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


def test_json_loads_still_accepts_the_depth_the_walk_now_refuses() -> None:
    # Given: the premise of the bug — the stdlib parser takes this body.
    assert isinstance(json.loads(_nested_body(_DEPTH)), dict)


def test_deeply_nested_object_raises_a_payload_error() -> None:
    with pytest.raises(RequestPayloadError) as caught:
        _ = parse_object(_nested_body(_DEPTH))

    assert "deep" in str(caught.value)


def test_deeply_nested_list_raises_a_payload_error() -> None:
    body = ('{"a":' + "[" * _DEPTH + "]" * _DEPTH + "}").encode("utf-8")

    with pytest.raises(RequestPayloadError):
        _ = parse_object(body)


def test_nesting_at_the_limit_still_parses() -> None:
    # The top-level object is depth 1, so MAX_NESTING_DEPTH objects fit.
    body = _nested_body(request_payload.MAX_NESTING_DEPTH)

    assert parse_object(body) == json.loads(body)


def test_deeply_nested_post_answers_400_instead_of_hanging_up(
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
            body=_nested_body(_DEPTH),
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
    assert "deep" in json.loads(payload)["error"]
