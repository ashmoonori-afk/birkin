from __future__ import annotations

import http.client
import threading
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from http.server import HTTPServer
from typing import NoReturn

import pytest

from birkin import config
from birkin.web.browser_security import (
    BrowserRequestDenied,
    browser_request_guard,
)
from birkin.web.external_origin import parse_web_external_url
from birkin.web import server as web_server


def _request(
    host: str,
    port: int,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    request_headers = dict(headers or {})
    _ = request_headers.setdefault("Host", host)
    connection.request(method, path, headers=request_headers)
    response = connection.getresponse()
    body = response.read()
    response_headers = dict(response.getheaders())
    connection.close()
    return response.status, response_headers, body


def _refuse_bind(*_args: object, **_kwargs: object) -> NoReturn:
    pytest.fail("remote listener bound without a valid HTTPS external URL")


@contextmanager
def _running_server(
    monkeypatch: pytest.MonkeyPatch,
    cfg: Mapping[str, object],
) -> Generator[tuple[int, str], None, None]:
    monkeypatch.setattr(web_server.config, "load_config", lambda: cfg)
    httpd = HTTPServer(("127.0.0.1", 0), web_server.Handler)
    port = int(httpd.server_address[1])
    nonce = web_server.listener_bootstrap_nonce(httpd)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, nonce
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def _bootstrap(
    *,
    host: str,
    port: int,
    nonce: str,
    forwarded_proto: str,
) -> tuple[str, dict[str, str]]:
    code, headers, _body = _request(
        host,
        port,
        "GET",
        f"/_bootstrap/{nonce}",
        headers={"X-Forwarded-Proto": forwarded_proto},
    )
    assert code == 303
    return headers["Set-Cookie"].split(";", 1)[0], headers


def test_remote_run_refuses_missing_https_external_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = {
        **config.DEFAULT_CONFIG,
        "web_remote_access": True,
        "web_remote_insecure_ack": True,
        "web_external_url": "",
    }
    monkeypatch.setattr(web_server.config, "load_config", lambda: cfg)
    monkeypatch.setattr(
        web_server,
        "HTTPServer",
        _refuse_bind,
    )

    assert web_server.run(port=8765, open_browser=False) == 2
    error = capsys.readouterr().err
    assert "web_external_url" in error
    assert "https://" in error


@pytest.mark.parametrize(
    "external_url",
    (
        "http://console.example",
        "console.example",
        "https://user@console.example",
        "https://console.example/webui",
        "https://console.example:not-a-port",
    ),
)
def test_remote_run_refuses_invalid_external_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    external_url: str,
) -> None:
    cfg = {
        **config.DEFAULT_CONFIG,
        "web_remote_access": True,
        "web_external_url": external_url,
    }
    monkeypatch.setattr(web_server.config, "load_config", lambda: cfg)
    monkeypatch.setattr(
        web_server,
        "HTTPServer",
        _refuse_bind,
    )

    assert web_server.run(port=8765, open_browser=False) == 2
    assert "web_external_url" in capsys.readouterr().err


def test_https_reverse_proxy_bootstrap_and_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = {
        **config.DEFAULT_CONFIG,
        "web_remote_access": True,
        "web_external_url": "https://console.example",
    }
    with _running_server(monkeypatch, cfg) as (port, nonce):
        cookie, headers = _bootstrap(
            host="console.example",
            port=port,
            nonce=nonce,
            forwarded_proto="http",
        )
        code, _, _ = _request(
            "console.example",
            port,
            "GET",
            "/api/workspace/sessions",
            headers={
                "Cookie": cookie,
                "Origin": "https://console.example",
                "Referer": "https://console.example/",
                "Sec-Fetch-Site": "same-origin",
                "X-Forwarded-Proto": "http",
            },
        )

    assert "Secure" in headers["Set-Cookie"]
    assert code == 200


def test_ssh_loopback_bootstrap_and_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = {
        **config.DEFAULT_CONFIG,
        "web_remote_access": False,
        "web_external_url": "",
    }
    with _running_server(monkeypatch, cfg) as (port, nonce):
        authority = f"127.0.0.1:{port}"
        cookie, headers = _bootstrap(
            host=authority,
            port=port,
            nonce=nonce,
            forwarded_proto="https",
        )
        code, _, _ = _request(
            authority,
            port,
            "GET",
            "/api/workspace/sessions",
            headers={
                "Cookie": cookie,
                "Origin": f"http://{authority}",
                "Referer": f"http://{authority}/",
                "Sec-Fetch-Site": "same-origin",
                "X-Forwarded-Proto": "https",
            },
        )

    assert "Secure" not in headers["Set-Cookie"]
    assert code == 200


def test_browser_guard_uses_configured_external_origin() -> None:
    guard = browser_request_guard(
        port=8787,
        capability="capability",
        bootstrap_nonce="nonce",
        external_origin="https://console.example",
    )

    assert guard.consume_bootstrap(
        "nonce",
        host="console.example",
    ) == "capability"
    guard.authorize(
        method="GET",
        path="/api/browser/status",
        host="console.example",
        origin="https://console.example",
        fetch_site="same-origin",
        content_type=None,
        cookie_capability="capability",
        header_capability=None,
    )
    with pytest.raises(BrowserRequestDenied, match="configured WebUI origin"):
        guard.authorize(
            method="GET",
            path="/api/browser/status",
            host="console.example",
            origin="http://console.example",
            fetch_site="same-origin",
            content_type=None,
            cookie_capability="capability",
            header_capability=None,
        )


def test_external_url_is_canonicalized_for_browser_headers() -> None:
    external = parse_web_external_url(
        "https://Console.Example.:443/"
    )

    assert external is not None
    assert external.origin == "https://console.example"
    assert external.authority == "console.example"
