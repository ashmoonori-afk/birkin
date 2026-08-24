from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from birkin.browser_aside_engine import SyncApi
from birkin.browser_aside_engine import BrowserContext, Playwright
from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_playwright import PersistentBrowserRuntime
from birkin.browser_aside_playwright_support import launch_isolated_context
from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.browser_aside_requests import BrowserRequestAuthority


def test_bundled_integrity_finishes_before_chromium_startup_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin import browser_aside_playwright as runtime_module

    order: list[str] = []
    wait_budgets: list[float | None] = []
    sentinel_api = cast(SyncApi, object())

    class ImmediateTimeoutEvent:
        def wait(self, _timeout: float | None = None) -> bool:
            wait_budgets.append(_timeout)
            return False

        def set(self) -> None:
            return

        def is_set(self) -> bool:
            return False

    class InertThread:
        def __init__(self, **_kwargs: object) -> None:
            order.append("thread-created")

        def start(self) -> None:
            order.append("thread-started")

    def load_api() -> SyncApi:
        order.append("integrity-complete")
        return sentinel_api

    monkeypatch.setattr(runtime_module, "Event", ImmediateTimeoutEvent)
    monkeypatch.setattr(runtime_module, "Thread", InertThread)
    monkeypatch.setattr(runtime_module, "load_sync_api", load_api)

    with pytest.raises(BrowserAsideError) as captured:
        _ = PersistentBrowserRuntime(
            session_id="session",
            generation=1,
            profile_dir=tmp_path / "profile",
            policy=BrowserEgressPolicy(),
            requests=cast(BrowserRequestAuthority, object()),
        )

    assert captured.value.code == "browser_start_timeout"
    assert wait_budgets == [60]
    assert order == [
        "integrity-complete",
        "thread-created",
        "thread-started",
    ]


def test_playwright_launch_budget_fits_inside_owner_readiness_budget(
    tmp_path: Path,
) -> None:
    options: dict[str, object] = {}
    sentinel_context = cast(BrowserContext, object())

    class Chromium:
        def launch_persistent_context(
            self,
            **kwargs: object,
        ) -> BrowserContext:
            options.update(kwargs)
            return sentinel_context

    class Runtime:
        chromium: Chromium = Chromium()

    context = launch_isolated_context(
        cast(Playwright, cast(object, Runtime())),
        tmp_path / "profile",
        "http://127.0.0.1:8000",
        ("username", "password"),
    )

    assert context is sentinel_context
    assert options["timeout"] == 45_000
