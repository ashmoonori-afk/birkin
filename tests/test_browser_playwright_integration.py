from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from birkin.browser import BrowserSession
from birkin.browser_playwright import PlaywrightDriver, playwright_browser_available
from birkin.sandbox import NetworkPolicy, SandboxPolicy

pytestmark = pytest.mark.browser_integration


def _browser_ready() -> bool:
    return (
        os.environ.get("BIRKIN_BROWSER_INTEGRATION") == "1"
        and importlib.util.find_spec("playwright") is not None
        and playwright_browser_available()
    )


@pytest.mark.skipif(
    not _browser_ready(),
    reason="set BIRKIN_BROWSER_INTEGRATION=1 and install Playwright Chromium",
)
def test_real_browser_drives_a_data_page_and_closes(tmp_path: Path) -> None:
    driver = PlaywrightDriver(headless=True)
    browser = BrowserSession(
        driver,
        SandboxPolicy(
            network=NetworkPolicy.ALLOWLIST,
            network_allowlist=("localhost",),
            write_paths=(".",),
        ),
        tmp_path,
    )
    try:
        # No network is needed for page setup; interaction is still real Chromium.
        browser.execute("document.body.innerHTML = '<button id=go>Go</button>'")
        browser.click("#go")
        shot = browser.screenshot("real-browser.png")
        assert shot.is_file() and shot.stat().st_size > 0
    finally:
        browser.close()
