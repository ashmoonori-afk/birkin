from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Generator
from contextlib import contextmanager
from http.server import HTTPServer
from typing import NoReturn

import pytest

from birkin import config
from birkin.web import server as web_server
from birkin.web.external_origin import parse_web_external_url


def _request(
    host: str,
    port: int,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    request_headers = dict(headers or {})
    _ = request_headers.setdefault("Host", host)
    connection.request("GET", path, headers=request_headers)
    response = connection.getresponse()
    body = response.read()
    response_headers = dict(response.getheaders())
    connection.close()
    return response.status, response_headers, body


@contextmanager
def _remote_server(
    monkeypatch: pytest.MonkeyPatch,
    *,
    a2a_enabled: bool = False,
) -> Generator[tuple[int, str], None, None]:
    cfg = {
        **config.DEFAULT_CONFIG,
        "a2a_enabled": a2a_enabled,
        "web_remote_access": True,
        "web_external_url": "https://console.example",
    }
    monkeypatch.setattr(web_server.config, "load_config", lambda: cfg)
    server = HTTPServer(("127.0.0.1", 0), web_server.Handler)
    port = int(server.server_address[1])
    nonce = web_server.listener_bootstrap_nonce(server)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, nonce
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def _capability_cookie(
    port: int,
    nonce: str,
) -> str:
    code, headers, _ = _request(
        "console.example:443",
        port,
        f"/_bootstrap/{nonce}",
    )
    assert code == 303
    return headers["Set-Cookie"].split(";", 1)[0]


def test_external_proxy_requires_capability_and_origin_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _remote_server(monkeypatch) as (port, nonce):
        assert _request("console.example", port, "/api/runs")[0] == 403
        cookie = _capability_cookie(port, nonce)
        hostile = _request(
            "console.example",
            port,
            "/api/runs",
            headers={
                "Cookie": cookie,
                "Origin": "https://evil.example",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        allowed = _request(
            "console.example",
            port,
            "/api/runs",
            headers={
                "Cookie": cookie,
                "Origin": "https://console.example",
                "Sec-Fetch-Site": "same-origin",
            },
        )

    assert hostile[0] == 403
    assert allowed[0] == 200


def test_agent_card_uses_external_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _remote_server(monkeypatch, a2a_enabled=True) as (port, nonce):
        cookie = _capability_cookie(port, nonce)
        code, _, body = _request(
            "console.example",
            port,
            "/.well-known/agent-card.json",
            headers={"Cookie": cookie},
        )

    assert code == 200
    assert json.loads(body)["url"] == "https://console.example/a2a"


@pytest.mark.parametrize(
    "value",
    (
        "https://%65xample.com",
        "https://127.1",
        "https://0x7f000001",
        "https://0x7f.1",
        "https://127.0x0.0.1",
        "https://evil.com\\trusted.example",
        "https://faß.de",
        " https://console.example",
    ),
)
def test_external_origin_rejects_browser_divergent_hosts(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="web_external_url"):
        _ = parse_web_external_url(value)


def test_external_origin_canonicalizes_ipv6() -> None:
    external = parse_web_external_url(
        "https://[0:0:0:0:0:0:0:1]:443"
    )

    assert external is not None
    assert external.origin == "https://[::1]"
    assert external.authorities == frozenset({"[::1]", "[::1]:443"})


def _refuse_bind(*_args: object, **_kwargs: object) -> NoReturn:
    pytest.fail("external URL reached bind while remote mode was disabled")


@pytest.mark.parametrize(
    "external_url",
    ("http://console.example", "https://console.example"),
)
def test_external_url_requires_remote_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    external_url: str,
) -> None:
    cfg = {
        **config.DEFAULT_CONFIG,
        "web_remote_access": False,
        "web_external_url": external_url,
    }
    monkeypatch.setattr(web_server.config, "load_config", lambda: cfg)
    monkeypatch.setattr(web_server, "HTTPServer", _refuse_bind)

    assert web_server.run(port=8765, open_browser=False) == 2
    assert "web_remote_access" in capsys.readouterr().err
