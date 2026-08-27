from __future__ import annotations

from collections.abc import Callable
from typing import cast, final

import pytest

from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.browser_contracts import (
    BrowserPolicyViolation,
    BrowserUnavailableError,
)
from birkin.browser_playwright import PlaywrightDriver
from birkin.sandbox import NetworkPolicy, SandboxPolicy


@final
class FakeEngineError(Exception):
    pass


@final
class FakePage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.goto_callback: Callable[[], None] | None = None
        self.goto_count = 0

    def on(self, _event: str, _handler: Callable[[object], None]) -> None:
        return

    def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: float,
    ) -> object:
        del wait_until, timeout
        self.goto_count += 1
        self.url = url
        if self.goto_callback is not None:
            self.goto_callback()
        return object()


@final
class FakeContext:
    def __init__(self) -> None:
        self.page = FakePage()
        self.closed = False

    def route(self, _pattern: str, _handler: Callable[[object], None]) -> None:
        return

    def new_page(self) -> FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True


@final
class FakeBrowser:
    def __init__(self) -> None:
        self.context = FakeContext()
        self.closed = False
        self.context_options: dict[str, object] = {}

    def new_context(self, **options: object) -> FakeContext:
        self.context_options = options
        return self.context

    def close(self) -> None:
        self.closed = True


@final
class FakeChromium:
    def __init__(self) -> None:
        self.browser = FakeBrowser()
        self.launch_options: dict[str, object] = {}
        self.failure: Exception | None = None

    def launch(self, **options: object) -> FakeBrowser:
        self.launch_options = options
        if self.failure is not None:
            raise self.failure
        return self.browser


@final
class FakePlaywright:
    def __init__(self) -> None:
        self.chromium = FakeChromium()
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


@final
class FakeManager:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright

    def start(self) -> FakePlaywright:
        return self.playwright


@final
class FakeApi:
    Error = FakeEngineError

    def __init__(self) -> None:
        self.playwright = FakePlaywright()

    def sync_playwright(self) -> FakeManager:
        return FakeManager(self.playwright)


@final
class FakeProxy:
    url = "http://127.0.0.1:43210"
    credentials = ("birkin", "proxy-secret")

    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.denials: list[BrowserAsideError] = []
        self.start_failure: RuntimeError | None = None

    def start(self) -> None:
        if self.start_failure is not None:
            raise self.start_failure
        self.started = True

    def close(self) -> None:
        self.closed = True

    def deny(self, error: BrowserAsideError) -> None:
        self.denials.append(error)

    def take_denial(self) -> BrowserAsideError | None:
        return self.denials.pop(0) if self.denials else None


def test_driver_launches_chromium_through_filtering_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi()
    proxy = FakeProxy()
    monkeypatch.setattr(
        PlaywrightDriver,
        "_api",
        staticmethod(lambda: cast(object, api)),
    )
    policy = BrowserEgressPolicy(
        policy=SandboxPolicy(
            network=NetworkPolicy.ALLOWLIST,
            network_allowlist=("public.example",),
        ),
    )
    driver = PlaywrightDriver(
        proxy_factory=lambda received: (
            proxy
            if received is policy
            else pytest.fail("driver replaced the Browser egress policy")
        ),
    )

    driver.start(policy)

    assert proxy.started
    assert api.playwright.chromium.launch_options == {
        "headless": True,
        "proxy": {
            "server": proxy.url,
            "username": proxy.credentials[0],
            "password": proxy.credentials[1],
        },
        "args": [
            "--proxy-bypass-list=<-loopback>",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        ],
    }
    assert api.playwright.chromium.browser.context_options == {
        "service_workers": "block",
    }

    driver.close()

    assert proxy.closed


def test_driver_closes_proxy_when_chromium_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi()
    api.playwright.chromium.failure = FakeEngineError("launch failed")
    proxy = FakeProxy()
    monkeypatch.setattr(
        PlaywrightDriver,
        "_api",
        staticmethod(lambda: cast(object, api)),
    )
    driver = PlaywrightDriver(proxy_factory=lambda _policy: proxy)

    with pytest.raises(BrowserUnavailableError):
        driver.start(BrowserEgressPolicy())

    assert proxy.started
    assert proxy.closed


def test_driver_closes_proxy_when_proxy_thread_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi()
    proxy = FakeProxy()
    proxy.start_failure = RuntimeError("thread start failed")
    monkeypatch.setattr(
        PlaywrightDriver,
        "_api",
        staticmethod(lambda: cast(object, api)),
    )
    driver = PlaywrightDriver(proxy_factory=lambda _policy: proxy)

    with pytest.raises(BrowserUnavailableError):
        driver.start(BrowserEgressPolicy())

    assert proxy.closed


def test_driver_translates_proxy_policy_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi()
    proxy = FakeProxy()
    monkeypatch.setattr(
        PlaywrightDriver,
        "_api",
        staticmethod(lambda: cast(object, api)),
    )
    driver = PlaywrightDriver(proxy_factory=lambda _policy: proxy)
    driver.start(BrowserEgressPolicy())
    api.playwright.chromium.browser.context.page.goto_callback = lambda: (
        proxy.deny(
            BrowserAsideError(
                "dns_rebinding_denied",
                "DNS answer changed after destination validation.",
                403,
            )
        )
    )

    with pytest.raises(
        BrowserPolicyViolation,
        match="DNS answer changed",
    ):
        _ = driver.navigate("https://example.com/")

    driver.close()


def test_driver_preserves_late_proxy_policy_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi()
    proxy = FakeProxy()
    monkeypatch.setattr(
        PlaywrightDriver,
        "_api",
        staticmethod(lambda: cast(object, api)),
    )
    driver = PlaywrightDriver(proxy_factory=lambda _policy: proxy)
    driver.start(BrowserEgressPolicy())
    assert driver.navigate("https://example.com/") == "https://example.com/"
    proxy.deny(
        BrowserAsideError(
            "dns_rebinding_denied",
            "DNS answer changed after destination validation.",
            403,
        )
    )

    with pytest.raises(BrowserPolicyViolation, match="DNS answer changed"):
        _ = driver.navigate("https://example.com/next")

    assert api.playwright.chromium.browser.context.page.goto_count == 1
    driver.close()
