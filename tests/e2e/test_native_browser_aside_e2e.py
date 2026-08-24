"""Authenticated Browser Aside through local HTTP and real Chromium."""

from __future__ import annotations

import pytest

from tests import native_browser_aside_support as support

pytestmark = pytest.mark.browser_integration


def test_authenticated_browser_aside_drives_real_chromium() -> None:
    if not support.browser_ready():
        pytest.skip("BIRKIN_BROWSER_INTEGRATION=1 and Playwright Chromium are mandatory")

    with support.browser_harness() as harness:
        harness.page.locator("#browser-aside-toggle").click()
        harness.page.locator("#browser-aside-url").fill(harness.fixture_url)
        harness.page.locator("#browser-aside-url").press("Enter")
        canvas = harness.page.locator("#browser-aside-canvas")
        harness.module.expect(canvas).to_have_attribute(
            "data-frame-ready",
            "true",
        )
        status = support.status(harness.page)
        assert status["display_url"].startswith("http://127.0.0.1:")
        assert canvas.get_attribute("data-frame-revision")
