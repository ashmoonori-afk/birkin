"""Typed engine boundary for the optional Browser Aside adapter."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol


class BrowserRequest(Protocol):
    url: str
    method: str
    post_data: str | None
    resource_type: str
    redirected_from: BrowserRequest | None

    def is_navigation_request(self) -> bool: ...


class BrowserRoute(Protocol):
    request: BrowserRequest

    def continue_(self) -> None: ...

    def abort(self, error_code: str = "failed") -> None: ...


class BrowserPage(Protocol):
    url: str

    def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: float,
    ) -> object: ...

    def screenshot(self, **kwargs: object) -> bytes: ...

    def on(
        self,
        event: str,
        handler: Callable[[object], None],
    ) -> None: ...

    def close(self) -> None: ...


class BrowserDialog(Protocol):
    def dismiss(self) -> None: ...


class BrowserFileChooser(Protocol):
    def set_files(self, files: Sequence[str]) -> None: ...


class BrowserDownload(Protocol):
    def cancel(self) -> None: ...


class BrowserContext(Protocol):
    pages: Sequence[BrowserPage]

    def new_page(self) -> BrowserPage: ...

    def route(
        self,
        url: str,
        handler: Callable[[BrowserRoute], None],
    ) -> None: ...

    def close(self) -> None: ...

    def clear_permissions(self) -> None: ...

    def on(
        self,
        event: str,
        handler: Callable[[object], None],
    ) -> None: ...

    def new_cdp_session(
        self,
        page: BrowserPage,
    ) -> BrowserCdpSession: ...

    def add_init_script(self, script: str) -> None: ...


class BrowserCdpSession(Protocol):
    def send(
        self,
        method: str,
        params: dict[str, object] | None = None,
    ) -> dict[str, object]: ...


class Chromium(Protocol):
    def launch_persistent_context(
        self,
        user_data_dir: str,
        **kwargs: object,
    ) -> BrowserContext: ...


class Playwright(Protocol):
    chromium: Chromium

    def stop(self) -> None: ...


class PlaywrightManager(Protocol):
    def start(self) -> Playwright: ...


class SyncApi(Protocol):
    Error: type[Exception]

    def sync_playwright(self) -> PlaywrightManager: ...


@dataclass(frozen=True, slots=True)
class BrowserRuntimeStatus:
    browser_session_id: str
    browser_generation: int
    browser_revision: int
    frame_revision: int
    display_url: str
    frame_digest: str | None
    frame_ref: str | None
