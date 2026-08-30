"""Legacy dashboard UI redirects while backend/API authority stays compatible."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import cast

import pytest

from birkin.web import server as web_server
from tests.local_http_support import local_http_timeout

HTML_PATH = (
    Path(__file__).resolve().parents[1]
    / "birkin"
    / "web"
    / "static"
    / "index.html"
)


@pytest.fixture
def server() -> Iterator[tuple[int, str]]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web_server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(httpd.server_address[1]), web_server.capability_token()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def _request(
    server: tuple[int, str],
    method: str,
    path: str,
    *,
    token: bool = False,
) -> tuple[int, dict[str, str], bytes]:
    port, capability = server
    headers = {"Host": "127.0.0.1"}
    if token:
        headers["X-Birkin-Token"] = capability
    connection = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=local_http_timeout()
    )
    connection.request(method, path, headers=headers)
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


@pytest.mark.parametrize(
    "path",
    ["/legacy-dashboard", "/dashboard", "/workbench"],
)
def test_legacy_dashboard_routes_redirect_to_workspace(
    server: tuple[int, str],
    path: str,
) -> None:
    code, headers, body = _request(server, "GET", path)

    assert code == 308
    assert headers["Location"] == "/"
    assert headers["Deprecation"] == "true"
    assert headers["Link"] == '</>; rel="successor-version"'
    assert body == b""


def test_legacy_backend_contracts_remain_available(
    server: tuple[int, str],
) -> None:
    for path in (
        "/api/status",
        "/api/jobs",
        "/api/runs",
        "/api/skills",
        "/api/contract",
    ):
        code, _, _ = _request(server, "GET", path)
        assert code == 200, path

    for path in (
        "/api/events",
        "/api/config",
        "/api/checkpoints",
        "/api/approvals",
    ):
        code, _, _ = _request(server, "GET", path, token=True)
        assert code == 200, path

    code, _, body = _request(server, "GET", "/api/contract")
    contract = cast(dict[str, object], json.loads(body))
    assert {"uistate", "tokens", "workspace_theme"} <= set(contract)


def test_root_is_workspace_with_events_and_bounded_approval_polling() -> None:
    source = HTML_PATH.read_text(encoding="utf-8")

    assert 'data-testid="workspace-shell"' in source
    assert "EventSource" in source
    assert source.count("setInterval(") == 1
    assert "const APPROVAL_REFRESH_INTERVAL_MS = 30_000;" in source
    assert "clearInterval(state.approvalRefreshTimer)" in source
