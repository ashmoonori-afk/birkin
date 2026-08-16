"""Thin optional Playwright implementation of :mod:`birkin.browser`."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast, final

from birkin.browser_contracts import (
    BrowserPolicyViolation,
    BrowserUnavailableError,
    ConsoleMessage,
    NetworkEvent,
)


class _Console(Protocol):
    type: str
    text: str


class _Request(Protocol):
    method: str
    url: str
    resource_type: str


class _Response(Protocol):
    request: _Request
    status: int


class _Route(Protocol):
    request: _Request

    def continue_(self) -> None: ...

    def abort(self, error_code: str = "failed") -> None: ...


class _Page(Protocol):
    url: str

    def on(self, event: str, callback: Callable[[object], None]) -> None: ...

    def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: float,
    ) -> object: ...

    def click(self, selector: str) -> None: ...

    def fill(self, selector: str, value: str) -> None: ...

    def press(self, selector: str, key: str) -> None: ...

    def evaluate(self, script: str) -> object: ...

    def screenshot(self, **kwargs: object) -> bytes: ...


class _Context(Protocol):
    def route(
        self,
        pattern: str,
        handler: Callable[[_Route], None],
    ) -> None: ...

    def new_page(self) -> _Page: ...

    def close(self) -> None: ...


class _Browser(Protocol):
    def new_context(self) -> _Context: ...

    def close(self) -> None: ...


class _Chromium(Protocol):
    def launch(self, *, headless: bool) -> _Browser: ...


class _Playwright(Protocol):
    chromium: _Chromium

    def stop(self) -> None: ...


class _Manager(Protocol):
    def start(self) -> _Playwright: ...


class _SyncApi(Protocol):
    Error: type[Exception]

    def sync_playwright(self) -> _Manager: ...


@final
class PlaywrightDriver:
    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._playwright: _Playwright | None = None
        self._browser: _Browser | None = None
        self._context: _Context | None = None
        self._page: _Page | None = None
        self._engine_error: type[Exception] = RuntimeError
        self._blocked: BrowserPolicyViolation | None = None
        self._console: list[ConsoleMessage] = []
        self._network: list[NetworkEvent] = []

    @staticmethod
    def _api() -> _SyncApi:
        module: ModuleType = importlib.import_module("playwright.sync_api")
        return cast(_SyncApi, cast(object, module))

    def start(self, request_guard: Callable[[str], None]) -> None:
        if self._page is not None:
            return
        try:
            api = self._api()
            self._engine_error = api.Error
            self._playwright = api.sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=self._headless
            )
            self._context = self._browser.new_context()
            self._context.route(
                "**/*",
                lambda route: self._route(route, request_guard),
            )
            self._page = self._context.new_page()
            self._page.on(
                "console",
                lambda message: self._on_console(
                    cast(_Console, message)
                ),
            )
            self._page.on(
                "request",
                lambda request: self._on_request(
                    cast(_Request, request)
                ),
            )
            self._page.on(
                "response",
                lambda response: self._on_response(
                    cast(_Response, response)
                ),
            )
        except (ImportError, self._engine_error) as exc:
            cleanup_failures = self._cleanup()
            if cleanup_failures:
                raise BrowserUnavailableError(
                    "Playwright startup failed and cleanup was incomplete."
                ) from cleanup_failures[0]
            raise BrowserUnavailableError(
                "Playwright Chromium is unavailable. Install birkin[browser] "
                + "and run `python -m playwright install chromium`."
            ) from exc

    def _route(
        self,
        route: _Route,
        guard: Callable[[str], None],
    ) -> None:
        try:
            guard(route.request.url)
        except BrowserPolicyViolation as exc:
            self._blocked = exc
            route.abort("blockedbyclient")
        else:
            route.continue_()

    def _on_console(self, message: _Console) -> None:
        self._console.append(ConsoleMessage(message.type, message.text))

    def _on_request(self, request: _Request) -> None:
        self._network.append(
            NetworkEvent(
                "request",
                request.method,
                request.url,
                None,
                request.resource_type,
            )
        )

    def _on_response(self, response: _Response) -> None:
        request = response.request
        self._network.append(
            NetworkEvent(
                "response",
                request.method,
                request.url,
                response.status,
                request.resource_type,
            )
        )

    def _call(self, operation: Callable[[], object]) -> object:
        if self._page is None:
            raise BrowserUnavailableError("browser driver is not started")
        self._blocked = None
        try:
            return operation()
        except self._engine_error as exc:
            if self._blocked is not None:
                raise self._blocked from exc
            raise BrowserUnavailableError(str(exc)) from exc

    def navigate(self, url: str) -> str:
        page = self._require_page()
        _ = self._call(
            lambda: page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        )
        return page.url

    def click(self, selector: str) -> None:
        page = self._require_page()
        _ = self._call(lambda: page.click(selector))

    def fill(self, selector: str, value: str) -> None:
        page = self._require_page()
        _ = self._call(lambda: page.fill(selector, value))

    def press(self, selector: str, key: str) -> None:
        page = self._require_page()
        _ = self._call(lambda: page.press(selector, key))

    def execute(self, script: str) -> object:
        page = self._require_page()
        return self._call(lambda: page.evaluate(script))

    def screenshot(self, path: Path, *, full_page: bool) -> None:
        page = self._require_page()
        _ = self._call(
            lambda: page.screenshot(path=str(path), full_page=full_page)
        )

    def evidence(
        self,
    ) -> tuple[list[ConsoleMessage], list[NetworkEvent]]:
        return list(self._console), list(self._network)

    def close(self) -> None:
        failures = self._cleanup()
        if failures:
            raise BrowserUnavailableError(
                "Playwright cleanup did not complete cleanly."
            ) from failures[0]

    def _cleanup(self) -> list[Exception]:
        failures: list[Exception] = []
        if self._context is not None:
            try:
                self._context.close()
            except self._engine_error as exc:
                failures.append(exc)
        if self._browser is not None:
            try:
                self._browser.close()
            except self._engine_error as exc:
                failures.append(exc)
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except self._engine_error as exc:
                failures.append(exc)
        self._clear()
        return failures

    def _clear(self) -> None:
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    def _require_page(self) -> _Page:
        if self._page is None:
            raise BrowserUnavailableError("browser driver is not started")
        return self._page


def playwright_browser_available() -> bool:
    driver = PlaywrightDriver()
    try:
        driver.start(lambda _url: None)
    except BrowserUnavailableError:
        return False
    driver.close()
    return True
