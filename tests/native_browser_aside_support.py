from __future__ import annotations

import importlib
import importlib.util
import json
import os
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import ModuleType, TracebackType
from typing import ClassVar, Protocol, cast, final
from urllib.parse import urlsplit

from birkin.browser_playwright import playwright_browser_available
from birkin.web import server as web_server

FIXTURE_TEXT = "BIRKIN-NATIVE-FRAME-7F3A"
FIRST_COLOR = (18, 52, 86)
SECOND_COLOR = (22, 101, 52)
WEBSOCKET_BLOCKED_COLOR = (24, 120, 70)


class Locator(Protocol):
    def click(self) -> None: ...

    def fill(self, value: str) -> None: ...

    def press(self, key: str) -> None: ...

    def evaluate(self, expression: str) -> object: ...

    def get_attribute(self, name: str) -> str | None: ...

    def focus(self) -> None: ...

    def count(self) -> int: ...


class Expectation(Protocol):
    def to_have_count(self, count: int) -> None: ...

    def to_have_attribute(self, name: str, value: str) -> None: ...

    def to_be_visible(self) -> None: ...


class Page(Protocol):
    def goto(self, url: str) -> object: ...

    def locator(self, selector: str) -> Locator: ...

    def evaluate(
        self,
        expression: str,
        arg: object | None = None,
    ) -> object: ...

    def wait_for_function(
        self,
        expression: str,
        arg: object,
    ) -> object: ...

    def set_default_timeout(self, timeout: float) -> None: ...

    def set_viewport_size(self, viewport_size: dict[str, int]) -> None: ...


class Browser(Protocol):
    def new_page(self, **kwargs: object) -> Page: ...

    def close(self) -> None: ...


class Chromium(Protocol):
    def launch(self, *, headless: bool) -> Browser: ...


class Playwright(Protocol):
    chromium: Chromium


class PlaywrightContext(Protocol):
    def __enter__(self) -> Playwright: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class PlaywrightModule(Protocol):
    def sync_playwright(self) -> PlaywrightContext: ...

    def expect(self, locator: Locator) -> Expectation: ...


def _quiet_log(
    self: BaseHTTPRequestHandler,
    format: str,
    *args: object,
) -> None:
    del self, format, args


@final
class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    page: ClassVar[bytes] = (
        "<!doctype html><html><head><title>Native Fixture</title></head>"
        "<body style='margin:0;color:white'>"
        f"<h1>{FIXTURE_TEXT}</h1><output id='counter'></output><script>"
        "const count=Number(localStorage.getItem('counter')||0)+1;"
        "localStorage.setItem('counter',String(count));"
        "document.querySelector('#counter').textContent=String(count);"
        "document.body.style.background=count===1"
        "?'rgb(18,52,86)':'rgb(22,101,52)';"
        "</script></body></html>"
    ).encode()
    post_count: ClassVar[int] = 0
    scripted_count: ClassVar[int] = 0
    log_message = _quiet_log

    def do_GET(self) -> None:
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/auto-form":
            body = (
                b"<form id='f' method='post' action='/submitted'>"
                + b"<input name='api_key' "
                + b"value='PRIVATE-SENTINEL-9911'>"
                + b"</form><script>f.submit()</script>"
            )
            self._body(body)
            return
        if self.path == "/auto-nav":
            self._body(b"<script>location.href='/scripted'</script>")
            return
        if self.path == "/websocket":
            self._body(
                b"<style>html,body{height:100%}</style>"
                + b"<body style='margin:0'><script>"
                + b"try { new WebSocket('ws://' + location.host + '/ws');"
                + b"document.body.style.background='rgb(180,30,30)' }"
                + b"catch { document.body.style.background="
                + b"'rgb(24,120,70)' }</script></body>"
            )
            return
        if self.path == "/scripted":
            type(self).scripted_count += 1
        self._body(self.page)

    def do_POST(self) -> None:
        type(self).post_count += 1
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _body(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        _ = self.wfile.write(body)


@contextmanager
def serve(
    handler: type[BaseHTTPRequestHandler],
) -> Generator[tuple[ThreadingHTTPServer, str]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def browser_ready() -> bool:
    return (
        os.environ.get("BIRKIN_BROWSER_INTEGRATION") == "1"
        and importlib.util.find_spec("playwright") is not None
        and playwright_browser_available()
    )


def playwright_module() -> PlaywrightModule:
    module: ModuleType = importlib.import_module("playwright.sync_api")
    return cast(PlaywrightModule, cast(object, module))


@dataclass(frozen=True)
class BrowserHarness:
    module: PlaywrightModule
    page: Page
    fixture_url: str
    web_url: str


def canvas_color(canvas: Locator) -> tuple[int, int, int]:
    color_raw = canvas.evaluate(
        """(node) => Array.from(
          node.getContext('2d').getImageData(2, 2, 1, 1).data
        ).slice(0, 3)"""
    )
    assert isinstance(color_raw, list)
    values = cast(list[object], color_raw)
    assert len(values) == 3
    assert all(isinstance(value, int) for value in values)
    return cast(tuple[int, int, int], tuple(values))


def colors_match(
    actual: tuple[int, int, int],
    expected: tuple[int, int, int],
    *,
    tolerance: int = 3,
) -> bool:
    return all(
        abs(left - right) <= tolerance
        for left, right in zip(actual, expected, strict=True)
    )


def status(page: Page) -> dict[str, object]:
    raw = page.evaluate(
        """() => {
          window.__birkinTestClient ||=
            sessionStorage.getItem('birkin-browser-client') ||
            crypto.randomUUID();
          return fetch('/api/browser-aside/status', {
            headers: {
              'X-Birkin-Browser-Client': window.__birkinTestClient,
            },
          })
          .then((response) => response.json())"""
        + "}"
    )
    assert isinstance(raw, dict)
    return cast(dict[str, object], raw)


def api(
    page: Page,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    raw = page.evaluate(
        """async ({method, path, payload}) => {
          window.__birkinTestClient ||=
            sessionStorage.getItem('birkin-browser-client') ||
            crypto.randomUUID();
          window.__birkinTestSequence = Math.max(
            window.__birkinTestSequence || 0,
            Number(sessionStorage.getItem(
              'birkin-browser-control-sequence'
            ) || 0),
          );
          const headers = {
            'Content-Type': 'application/json',
            'X-Birkin-Browser-Client': window.__birkinTestClient,
          };
          const options = {method, headers};
          if (
            path === '/api/browser-aside/navigate' ||
            (method === 'DELETE' &&
              path === '/api/browser-aside/session')
          ) {
            const status = await fetch(
              '/api/browser-aside/status',
              {headers}
            ).then((response) => response.json());
            window.__birkinTestSequence += 1;
            sessionStorage.setItem(
              'birkin-browser-control-sequence',
              String(window.__birkinTestSequence),
            );
            if (path === '/api/browser-aside/navigate') {
              payload = {
                ...payload,
                browser_generation: status.browser_generation,
                browser_revision: status.browser_revision,
                control_epoch: status.control_epoch,
                control_sequence: window.__birkinTestSequence,
              };
            } else {
              path += `?generation=${status.browser_generation}` +
                `&revision=${status.browser_revision}` +
                `&control_epoch=${status.control_epoch}` +
                `&control_sequence=${window.__birkinTestSequence}`;
            }
          }
          if (payload !== null) options.body = JSON.stringify(payload);
          const response = await fetch(path, options);
          return {status: response.status, body: await response.json()};
        }""",
        {"method": method, "path": path, "payload": payload},
    )
    assert isinstance(raw, dict)
    response = cast(dict[str, object], raw)
    response_status = response["status"]
    body = response["body"]
    assert isinstance(response_status, int)
    assert isinstance(body, dict)
    return response_status, cast(dict[str, object], body)


@contextmanager
def browser_harness() -> Generator[BrowserHarness]:
    module = playwright_module()
    previous_rules = os.environ.get(
        "BIRKIN_BROWSER_PRIVATE_NETWORK_RULES"
    )
    previous_controls = os.environ.get(
        "BIRKIN_BROWSER_CONTROL_ADDRESSES"
    )
    with serve(FixtureHandler) as (_, fixture_url):
        fixture = urlsplit(fixture_url)
        assert fixture.hostname is not None
        assert fixture.port is not None
        os.environ["BIRKIN_BROWSER_PRIVATE_NETWORK_RULES"] = json.dumps([
            {
                "host": fixture.hostname,
                "cidr": "127.0.0.1/32",
                "port": fixture.port,
            }
        ])
        try:
            with (
                serve(web_server.Handler) as (web_server_instance, web_url),
                module.sync_playwright() as playwright,
            ):
                web = urlsplit(web_url)
                assert web.port is not None
                os.environ["BIRKIN_BROWSER_CONTROL_ADDRESSES"] = (
                    f"127.0.0.1:{web.port},localhost:{web.port}"
                )
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1000}
                )
                page.set_default_timeout(5_000)
                token = web_server.listener_bootstrap_nonce(
                    web_server_instance
                )
                _ = page.goto(f"{web_url}/_bootstrap/{token}")
                try:
                    yield BrowserHarness(
                        module,
                        page,
                        fixture_url,
                        web_url,
                    )
                finally:
                    try:
                        _ = api(
                            page,
                            "DELETE",
                            "/api/browser-aside/session",
                        )
                    finally:
                        browser.close()
        finally:
            if previous_rules is None:
                del os.environ["BIRKIN_BROWSER_PRIVATE_NETWORK_RULES"]
            else:
                os.environ[
                    "BIRKIN_BROWSER_PRIVATE_NETWORK_RULES"
                ] = previous_rules
            if previous_controls is None:
                _ = os.environ.pop(
                    "BIRKIN_BROWSER_CONTROL_ADDRESSES",
                    None,
                )
            else:
                os.environ[
                    "BIRKIN_BROWSER_CONTROL_ADDRESSES"
                ] = previous_controls
