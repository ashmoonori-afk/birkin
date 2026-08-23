from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from birkin.browser_aside_engine import SyncApi
from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_playwright import PersistentBrowserRuntime
from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.browser_aside_requests import BrowserRequestAuthority


def test_bundled_integrity_finishes_before_chromium_startup_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin import browser_aside_playwright as runtime_module

    order: list[str] = []
    sentinel_api = cast(SyncApi, object())

    class ImmediateTimeoutEvent:
        def wait(self, _timeout: float | None = None) -> bool:
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
    assert order == [
        "integrity-complete",
        "thread-created",
        "thread-started",
    ]
