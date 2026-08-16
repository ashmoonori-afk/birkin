from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

from birkin import store
from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_service import BrowserAsideService


def test_failed_start_does_not_publish_live_browser_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from birkin import browser_aside_service

    events: list[dict[str, object]] = []

    def unavailable_runtime(**_kwargs: object) -> NoReturn:
        raise BrowserAsideError(
            "browser_unavailable",
            "Chromium is unavailable.",
            503,
        )

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setattr(
        store,
        "append_ledger",
        events.append,
    )
    monkeypatch.setattr(
        browser_aside_service,
        "PersistentBrowserRuntime",
        unavailable_runtime,
    )
    service = BrowserAsideService()

    for _ in range(2):
        with pytest.raises(
            BrowserAsideError,
            match="Chromium is unavailable",
        ):
            _ = service.start()

    assert events == []
