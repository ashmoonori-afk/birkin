from __future__ import annotations

import importlib.util
import os

import pytest

from birkin.browser_playwright import playwright_browser_available
from tests import native_browser_aside_support as SUPPORT

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(
        not (
            os.environ.get("BIRKIN_BROWSER_INTEGRATION") == "1"
            and importlib.util.find_spec("playwright") is not None
            and playwright_browser_available()
        ),
        reason="requires opt-in Playwright Chromium",
    ),
]


def test_context_and_page_persist_across_navigation() -> None:
    with SUPPORT.browser_harness() as harness:
        toggle = harness.page.locator("#browser-aside-toggle")
        toggle.click()
        url = harness.page.locator("#browser-aside-url")
        url.fill(harness.fixture_url)
        url.press("Enter")
        canvas = harness.page.locator("#browser-aside-canvas")
        harness.module.expect(canvas).to_have_attribute(
            "data-frame-revision",
            "1",
        )
        before = SUPPORT.status(harness.page)
        assert SUPPORT.colors_match(
            SUPPORT.canvas_color(canvas),
            SUPPORT.FIRST_COLOR,
        )

        url.press("Enter")
        harness.module.expect(canvas).to_have_attribute(
            "data-frame-revision",
            "2",
        )
        after = SUPPORT.status(harness.page)

        assert after["persistent"] is True
        assert (
            after["browser_session_id"]
            == before["browser_session_id"]
        )
        assert (
            after["browser_generation"]
            == before["browser_generation"]
        )
        assert SUPPORT.colors_match(
            SUPPORT.canvas_color(canvas),
            SUPPORT.SECOND_COLOR,
        )


def test_close_reconciles_concurrent_page_control_sequence() -> None:
    with SUPPORT.browser_harness() as harness:
        start_status, _ = SUPPORT.api(
            harness.page,
            "POST",
            "/api/browser-aside/session",
            {},
        )
        assert start_status == 201
        navigate_status, _ = SUPPORT.api(
            harness.page,
            "POST",
            "/api/browser-aside/navigate",
            {"url": harness.fixture_url},
        )
        assert navigate_status == 200
        _ = harness.page.evaluate(
            """() => {
              const originalFetch = window.fetch.bind(window);
              window.__birkinTestSequence = 0;
              sessionStorage.setItem(
                "birkin-browser-control-sequence", "0"
              );
              let reconcileSequence = true;
              window.fetch = async (input, init = {}) => {
                const url = typeof input === "string" ? input : input.url;
                const response = await originalFetch(input, init);
                if (
                  reconcileSequence &&
                  url === "/api/browser-aside/status"
                ) {
                  reconcileSequence = false;
                  sessionStorage.setItem(
                    "birkin-browser-control-sequence", "1"
                  );
                }
                return response;
              };
            }"""
        )

        close_status, closed = SUPPORT.api(
            harness.page,
            "DELETE",
            "/api/browser-aside/session",
        )

        assert close_status == 200
        assert closed["cleanup"] == "clean"


def test_close_releases_profile_for_next_persistent_context() -> None:
    with SUPPORT.browser_harness() as harness:
        toggle = harness.page.locator("#browser-aside-toggle")
        toggle.click()
        url = harness.page.locator("#browser-aside-url")
        url.fill(harness.fixture_url)
        url.press("Enter")
        canvas = harness.page.locator("#browser-aside-canvas")
        harness.module.expect(canvas).to_have_attribute(
            "data-frame-ready",
            "true",
        )
        before = SUPPORT.status(harness.page)

        close_status, closed = SUPPORT.api(
            harness.page,
            "DELETE",
            "/api/browser-aside/session",
        )
        assert close_status == 200
        assert closed["cleanup"] == "clean"

        toggle.click()
        toggle.click()
        url.press("Enter")
        harness.module.expect(canvas).to_have_attribute(
            "data-frame-ready",
            "true",
        )
        after = SUPPORT.status(harness.page)
        before_generation = before["browser_generation"]
        after_generation = after["browser_generation"]

        assert (
            after["browser_session_id"]
            != before["browser_session_id"]
        )
        assert isinstance(before_generation, int)
        assert isinstance(after_generation, int)
        assert after_generation > before_generation
