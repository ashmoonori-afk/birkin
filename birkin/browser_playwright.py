"""Thin optional Playwright implementation of :mod:`birkin.browser`."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .browser import (
    BrowserPolicyViolation,
    BrowserUnavailableError,
    ConsoleMessage,
    NetworkEvent,
)


class PlaywrightDriver:
    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._blocked: BrowserPolicyViolation | None = None
        self._console: list[ConsoleMessage] = []
        self._network: list[NetworkEvent] = []

    def start(self, request_guard: Callable[[str], None]) -> None:
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self._headless)
            self._context = self._browser.new_context()
            self._context.route("**/*", lambda route: self._route(route, request_guard))
            self._page = self._context.new_page()
            self._page.on("console", self._on_console)
            self._page.on("request", self._on_request)
            self._page.on("response", self._on_response)
        except ImportError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise BrowserUnavailableError(f"Playwright Chromium failed to start: {exc}") from exc

    def _route(self, route: Any, guard: Callable[[str], None]) -> None:
        try:
            guard(str(route.request.url))
        except BrowserPolicyViolation as exc:
            self._blocked = exc
            route.abort("blockedbyclient")
            return
        route.continue_()

    def _on_console(self, message: Any) -> None:
        self._console.append(ConsoleMessage(str(message.type), str(message.text)))

    def _on_request(self, request: Any) -> None:
        self._network.append(NetworkEvent(
            "request", str(request.method), str(request.url), None,
            str(request.resource_type),
        ))

    def _on_response(self, response: Any) -> None:
        request = response.request
        self._network.append(NetworkEvent(
            "response", str(request.method), str(response.url),
            int(response.status), str(request.resource_type),
        ))

    def _call(self, operation: Callable[[], Any]) -> Any:
        self._blocked = None
        try:
            result = operation()
        except Exception as exc:
            if self._blocked is not None:
                raise self._blocked from exc
            raise
        if self._blocked is not None:
            raise self._blocked
        return result

    def navigate(self, url: str) -> str:
        self._call(lambda: self._page.goto(url, wait_until="networkidle"))
        return str(self._page.title())

    def click(self, selector: str) -> None:
        self._call(lambda: self._page.click(selector))

    def fill(self, selector: str, value: str) -> None:
        self._call(lambda: self._page.fill(selector, value))

    def press(self, selector: str, key: str) -> None:
        self._call(lambda: self._page.press(selector, key))

    def execute(self, script: str) -> object:
        return self._call(lambda: self._page.evaluate(script))

    def screenshot(self, path: Path, *, full_page: bool) -> None:
        self._call(lambda: self._page.screenshot(path=str(path), full_page=full_page))

    def evidence(self) -> tuple[list[ConsoleMessage], list[NetworkEvent]]:
        return list(self._console), list(self._network)

    def close(self) -> None:
        for resource in (self._context, self._browser, self._playwright):
            if resource is not None:
                try:
                    resource.close() if resource is not self._playwright else resource.stop()
                except Exception:
                    pass
        self._page = self._context = self._browser = self._playwright = None


def playwright_browser_available() -> bool:
    """Return whether the package and its Chromium executable are usable."""
    driver = PlaywrightDriver()
    try:
        driver.start(lambda _url: None)
    except (ImportError, BrowserUnavailableError):
        return False
    finally:
        driver.close()
    return True
