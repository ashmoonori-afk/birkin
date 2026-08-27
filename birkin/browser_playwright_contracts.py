"""Typed seams for the optional synchronous Playwright adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from birkin.browser_aside_errors import BrowserAsideError


class ConsoleLike(Protocol):
    type: str
    text: str


class RequestLike(Protocol):
    method: str
    url: str
    resource_type: str


class ResponseLike(Protocol):
    request: RequestLike
    status: int


class RouteLike(Protocol):
    request: RequestLike

    def continue_(self) -> None: ...

    def abort(self, error_code: str = "failed") -> None: ...


class PageLike(Protocol):
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


class ContextLike(Protocol):
    def route(
        self,
        pattern: str,
        handler: Callable[[RouteLike], None],
    ) -> None: ...

    def new_page(self) -> PageLike: ...

    def close(self) -> None: ...


class BrowserLike(Protocol):
    def new_context(
        self,
        *,
        service_workers: str,
    ) -> ContextLike: ...

    def close(self) -> None: ...


class ChromiumLike(Protocol):
    def launch(
        self,
        *,
        headless: bool,
        proxy: dict[str, str],
        args: list[str],
    ) -> BrowserLike: ...


class PlaywrightLike(Protocol):
    chromium: ChromiumLike

    def stop(self) -> None: ...


class ManagerLike(Protocol):
    def start(self) -> PlaywrightLike: ...


class SyncApiLike(Protocol):
    Error: type[Exception]

    def sync_playwright(self) -> ManagerLike: ...


class FilteringProxyLike(Protocol):
    @property
    def url(self) -> str: ...

    @property
    def credentials(self) -> tuple[str, str]: ...

    def start(self) -> None: ...

    def close(self) -> None: ...

    def take_denial(self) -> BrowserAsideError | None: ...
