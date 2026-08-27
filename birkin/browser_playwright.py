"""Thin optional Playwright implementation of :mod:`birkin.browser`."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import cast, final

from birkin.browser_contracts import (
    BrowserPolicyViolation,
    BrowserUnavailableError,
    ConsoleMessage,
    NetworkEvent,
)
from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.browser_aside_proxy import BrowserFilteringProxy
from birkin.browser_playwright_contracts import (
    BrowserLike,
    ConsoleLike,
    ContextLike,
    FilteringProxyLike,
    PageLike,
    PlaywrightLike,
    RequestLike,
    ResponseLike,
    RouteLike,
    SyncApiLike,
)

ProxyFactory = Callable[[BrowserEgressPolicy], FilteringProxyLike]


@final
class PlaywrightDriver:
    def __init__(
        self,
        *,
        headless: bool = True,
        proxy_factory: ProxyFactory = BrowserFilteringProxy,
    ) -> None:
        self._headless = headless
        self._proxy_factory = proxy_factory
        self._proxy: FilteringProxyLike | None = None
        self._playwright: PlaywrightLike | None = None
        self._browser: BrowserLike | None = None
        self._context: ContextLike | None = None
        self._page: PageLike | None = None
        self._engine_error: type[Exception] = RuntimeError
        self._blocked: BrowserPolicyViolation | None = None
        self._console: list[ConsoleMessage] = []
        self._network: list[NetworkEvent] = []

    @staticmethod
    def _api() -> SyncApiLike:
        module: ModuleType = importlib.import_module("playwright.sync_api")
        return cast(SyncApiLike, cast(object, module))

    def start(self, policy: BrowserEgressPolicy) -> None:
        if self._page is not None:
            return
        try:
            api = self._api()
            self._engine_error = api.Error
            self._proxy = self._proxy_factory(policy)
            self._proxy.start()
            username, password = self._proxy.credentials
            self._playwright = api.sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=self._headless,
                proxy={
                    "server": self._proxy.url,
                    "username": username,
                    "password": password,
                },
                args=[
                    "--proxy-bypass-list=<-loopback>",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                ],
            )
            self._context = self._browser.new_context(service_workers="block")
            self._context.route(
                "**/*",
                lambda route: self._route(route, policy),
            )
            self._page = self._context.new_page()
            self._page.on(
                "console",
                lambda message: self._on_console(
                    cast(ConsoleLike, message)
                ),
            )
            self._page.on(
                "request",
                lambda request: self._on_request(
                    cast(RequestLike, request)
                ),
            )
            self._page.on(
                "response",
                lambda response: self._on_response(
                    cast(ResponseLike, response)
                ),
            )
        except (
            ImportError,
            self._engine_error,
            BrowserAsideError,
            OSError,
            RuntimeError,
        ) as exc:
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
        route: RouteLike,
        policy: BrowserEgressPolicy,
    ) -> None:
        try:
            policy.check_navigation(route.request.url)
        except BrowserAsideError as exc:
            self._blocked = BrowserPolicyViolation(exc.message)
            route.abort("blockedbyclient")
        else:
            route.continue_()

    def _on_console(self, message: ConsoleLike) -> None:
        self._console.append(ConsoleMessage(message.type, message.text))

    def _on_request(self, request: RequestLike) -> None:
        self._network.append(
            NetworkEvent(
                "request",
                request.method,
                request.url,
                None,
                request.resource_type,
            )
        )

    def _on_response(self, response: ResponseLike) -> None:
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
        if failure := self._take_policy_failure():
            raise failure
        try:
            result = operation()
        except self._engine_error as exc:
            if failure := self._take_policy_failure():
                raise failure from exc
            raise BrowserUnavailableError(str(exc)) from exc
        if failure := self._take_policy_failure():
            raise failure
        return result

    def _take_policy_failure(self) -> BrowserPolicyViolation | None:
        if self._blocked is not None:
            return self._blocked
        if self._proxy is not None:
            denial = self._proxy.take_denial()
            if denial is not None:
                return BrowserPolicyViolation(denial.message)
        return None

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
        if self._proxy is not None:
            try:
                self._proxy.close()
            except (BrowserAsideError, OSError) as exc:
                failures.append(exc)
        self._clear()
        return failures

    def _clear(self) -> None:
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._proxy = None

    def _require_page(self) -> PageLike:
        if self._page is None:
            raise BrowserUnavailableError("browser driver is not started")
        return self._page


def playwright_browser_available() -> bool:
    driver = PlaywrightDriver()
    try:
        driver.start(BrowserEgressPolicy())
    except BrowserUnavailableError:
        return False
    driver.close()
    return True
