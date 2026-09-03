"""Characterize HTTP route selection before handler dispatch is extracted."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from http.server import HTTPServer

import pytest

from birkin.web import server as web_server
from birkin.web.routes import GetRoute, PostRoute, match_get, match_post
from tests.local_http_support import local_http_timeout


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


def request(
    server: tuple[int, str],
    method: str,
    path: str,
    *,
    authenticated: bool = False,
    body: object | None = None,
) -> tuple[int, dict[str, str], bytes]:
    port, token = server
    headers = {"Host": "127.0.0.1"}
    if authenticated:
        headers["X-Birkin-Token"] = token
    encoded = None
    if body is not None:
        encoded = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    connection = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=local_http_timeout()
    )
    connection.request(method, path, body=encoded, headers=headers)
    response = connection.getresponse()
    payload = response.read()
    result = response.status, dict(response.getheaders()), payload
    connection.close()
    return result


@pytest.mark.parametrize("path", ["/favicon.ico", "/favicon.ico?cache=1"])
def test_favicon_matching_ignores_query(server: tuple[int, str], path: str) -> None:
    status, headers, body = request(server, "GET", path)
    assert (status, headers["Content-Type"], body) == (204, "image/x-icon", b"")


@pytest.mark.parametrize("path", ["/dashboard", "/workbench?from=old"])
def test_legacy_ui_matching_ignores_query(server: tuple[int, str], path: str) -> None:
    status, headers, body = request(server, "GET", path)
    assert (status, headers["Location"], body) == (308, "/", b"")
    assert headers["Deprecation"] == "true"


def test_root_query_is_not_the_root_route(server: tuple[int, str]) -> None:
    status, headers, body = request(server, "GET", "/?query=1")
    assert (status, headers["Content-Type"], body) == (404, "text/plain", b"not found")


def test_checkpoint_prefix_retains_json_not_found_semantics(
    server: tuple[int, str],
) -> None:
    status, headers, body = request(
        server, "GET", "/api/checkpoints-unknown", authenticated=True
    )
    assert status == 404
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(body) == {"error": "checkpoint route not found"}


@pytest.mark.parametrize(
    ("path", "expected_status", "expected_body"),
    [
        ("/api/nope", 404, b"not found"),
        ("/api/checkpoints/not-a-hash/restore", 400, b"invalid checkpoint id"),
    ],
)
def test_authenticated_post_invalid_route_selection(
    server: tuple[int, str],
    path: str,
    expected_status: int,
    expected_body: bytes,
) -> None:
    status, _, body = request(server, "POST", path, authenticated=True, body={})
    assert status == expected_status
    assert expected_body in body


def test_get_host_gate_precedes_public_route_dispatch(server: tuple[int, str]) -> None:
    port, _ = server
    connection = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=local_http_timeout()
    )
    connection.request("GET", "/api/status", headers={"Host": "evil.example"})
    response = connection.getresponse()
    body = response.read()
    connection.close()
    assert (response.status, body) == (403, b"forbidden host")


def test_every_get_route_variant_is_reachable_from_characterized_paths() -> None:
    paths = [
        "/api/browser-aside/status",
        "/favicon.ico",
        "/dashboard",
        "/api/workspace/sessions",
        "/_bootstrap/nonce",
        "/",
        "/api/status",
        "/api/approvals/000000000000/diff",
        "/api/config",
        "/api/agent-runs",
        "/api/agent-runs/000000000000",
        "/api/actions/000000000000/receipt",
        "/api/checkpoints",
        "/api/events",
        "/api/contract",
        "/api/jobs",
        "/api/runs",
        "/api/approvals",
        "/api/skills",
        "/.well-known/agent-card.json",
        "/not-found",
    ]
    assert {match_get(path).route for path in paths} == set(GetRoute)


def test_every_post_route_variant_is_reachable_from_characterized_paths() -> None:
    paths = [
        "/api/browser-aside/session",
        "/api/workspace/sessions",
        "/a2a",
        "/api/context",
        "/api/agent-runs/000000000000/control",
        "/api/checkpoints/abcd/restore",
        "/api/checkpoints/nope/restore",
        "/api/approvals",
        "/not-found",
    ]
    assert {match_post(path).route for path in paths} == set(PostRoute)


class _UnreachableRouteMatch:
    route: object = object()
    identifier: str = ""
    action: str = ""


def _host_ok(_handler: web_server.Handler) -> bool:
    return True


def _unreachable_route(_path: str) -> _UnreachableRouteMatch:
    return _UnreachableRouteMatch()


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_unreachable_route_variant_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    handler = object.__new__(web_server.Handler)
    handler.path = "/sentinel"
    monkeypatch.setattr(web_server.Handler, "_host_ok", _host_ok)
    if method == "GET":
        monkeypatch.setattr(web_server, "match_get", _unreachable_route)
        invoke = handler.do_GET
    else:
        monkeypatch.setattr(web_server, "match_post", _unreachable_route)
        invoke = handler.do_POST
    with pytest.raises(AssertionError):
        invoke()


def test_browser_post_bypasses_shared_admission_but_other_routes_do_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = object.__new__(web_server.Handler)
    handler.path = "/api/browser-aside/session"
    calls: list[str] = []

    def handle_browser(_handler: web_server.Handler) -> None:
        calls.append("browser")

    def admit(_handler: web_server.Handler) -> bool:
        calls.append("admit")
        return True

    def drain(_handler: web_server.Handler) -> None:
        calls.append("drain")

    def send(
        _handler: web_server.Handler,
        _code: int,
        _body: bytes,
        _content_type: str,
        _headers: dict[str, str] | None = None,
    ) -> None:
        calls.append("send")

    monkeypatch.setattr(web_server.Handler, "_handle_browser_post", handle_browser)
    monkeypatch.setattr(web_server.Handler, "_admit_post", admit)
    handler.do_POST()
    assert calls == ["browser"]

    handler.path = "/not-found"
    monkeypatch.setattr(web_server.Handler, "_drain_body", drain)
    monkeypatch.setattr(web_server.Handler, "_send", send)
    handler.do_POST()
    assert calls == ["browser", "admit", "drain", "send"]
