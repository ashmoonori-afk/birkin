from __future__ import annotations

import pytest

from tests import native_browser_aside_support as SUPPORT

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(
        not SUPPORT.browser_ready(),
        reason="set BIRKIN_BROWSER_INTEGRATION=1 and install Playwright Chromium",
    ),
]
def test_open_navigate_and_capture_real_browser_frame() -> None:
    with SUPPORT.browser_harness() as harness:
        toggle = harness.page.locator("#browser-aside-toggle")
        harness.module.expect(toggle).to_have_count(1)
        toggle.click()
        harness.page.locator("#browser-aside-url").fill(harness.fixture_url)
        harness.page.locator("#browser-aside-url").press("Enter")

        canvas = harness.page.locator("#browser-aside-canvas")
        harness.module.expect(canvas).to_have_attribute(
            "data-frame-ready", "true"
        )
        assert SUPPORT.colors_match(
            SUPPORT.canvas_color(canvas),
            SUPPORT.FIRST_COLOR,
        )

        status = SUPPORT.status(harness.page)
        assert status["engine"] == "chromium"
        assert status["persistent"] is True
        assert status["display_url"] == harness.fixture_url + "/"
        assert status["control_owner_kind"] == "human"
def test_collapse_preserves_persistent_browser_session() -> None:
    with SUPPORT.browser_harness() as harness:
        toggle = harness.page.locator("#browser-aside-toggle")
        toggle.click()
        url = harness.page.locator("#browser-aside-url")
        url.fill(harness.fixture_url)
        url.press("Enter")
        canvas = harness.page.locator("#browser-aside-canvas")
        harness.module.expect(canvas).to_have_attribute(
            "data-frame-ready", "true"
        )
        before = SUPPORT.status(harness.page)
        first_revision = canvas.get_attribute("data-frame-revision")
        assert isinstance(first_revision, str)
        assert SUPPORT.colors_match(
            SUPPORT.canvas_color(canvas),
            SUPPORT.FIRST_COLOR,
        )

        toggle.click()
        harness.module.expect(toggle).to_have_attribute(
            "aria-expanded", "false"
        )
        collapsed_width = harness.page.evaluate(
            "() => document.querySelector('.main').getBoundingClientRect().width"
        )
        assert isinstance(collapsed_width, (int, float))
        assert collapsed_width > 1200

        toggle.click()
        url.press("Enter")
        _ = harness.page.wait_for_function(
            """(revision) => document.querySelector(
                  '#browser-aside-canvas'
                ).dataset.frameRevision !== revision &&
                document.querySelector(
                  '#browser-aside-canvas'
                ).dataset.frameRevision !== '0' &&
                document.querySelector(
                  '#browser-aside-canvas'
                ).dataset.frameReady === 'true'""",
            arg=first_revision,
        )
        after = SUPPORT.status(harness.page)
        assert after["browser_session_id"] == before["browser_session_id"]
        assert SUPPORT.colors_match(
            SUPPORT.canvas_color(canvas),
            SUPPORT.SECOND_COLOR,
        )


def test_new_session_generation_never_reuses_old_frame_revision() -> None:
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
        url.press("Enter")
        harness.module.expect(canvas).to_have_attribute(
            "data-frame-revision",
            "2",
        )
        old_generation = canvas.get_attribute(
            "data-browser-generation"
        )

        close_status, _ = SUPPORT.api(
            harness.page,
            "DELETE",
            "/api/browser-aside/session",
        )
        assert close_status == 200
        toggle.click()
        toggle.click()
        url.press("Enter")
        _ = harness.page.wait_for_function(
            """(generation) => {
              const canvas = document.querySelector(
                '#browser-aside-canvas'
              );
              return canvas.dataset.browserGeneration !== generation &&
                canvas.dataset.frameRevision === '1';
            }""",
            arg=old_generation,
        )
        assert SUPPORT.colors_match(
            SUPPORT.canvas_color(canvas),
            SUPPORT.FIRST_COLOR,
        )


def test_frame_poll_refreshes_after_out_of_band_navigation() -> None:
    with SUPPORT.browser_harness() as harness:
        harness.page.locator("#browser-aside-toggle").click()
        url = harness.page.locator("#browser-aside-url")
        url.fill(harness.fixture_url)
        url.press("Enter")
        canvas = harness.page.locator("#browser-aside-canvas")
        harness.module.expect(canvas).to_have_attribute(
            "data-frame-ready",
            "true",
        )
        first_revision = canvas.get_attribute("data-frame-revision")
        assert isinstance(first_revision, str)
        assert SUPPORT.colors_match(
            SUPPORT.canvas_color(canvas),
            SUPPORT.FIRST_COLOR,
        )
        _ = harness.page.evaluate(
            """() => {
              window.__browserAsideFrameEvents = 0;
              addEventListener('browser-aside-frame', () => {
                window.__browserAsideFrameEvents += 1;
              });
            }"""
        )

        status, _ = SUPPORT.api(
            harness.page,
            "POST",
            "/api/browser-aside/navigate",
            {"url": harness.fixture_url},
        )
        assert status == 200
        _ = harness.page.wait_for_function(
            """(revision) => {
              const canvas = document.querySelector(
                '#browser-aside-canvas'
              );
              return canvas.dataset.frameRevision !== revision &&
                window.__browserAsideFrameEvents > 0;
            }""",
            arg=first_revision,
        )
        assert SUPPORT.colors_match(
            SUPPORT.canvas_color(canvas),
            SUPPORT.SECOND_COLOR,
        )


def test_frame_rejects_stale_browser_generation() -> None:
    with SUPPORT.browser_harness() as harness:
        _, started = SUPPORT.api(
            harness.page,
            "POST",
            "/api/browser-aside/session",
            {},
        )
        generation = started["browser_generation"]
        assert isinstance(generation, int)
        status, body = SUPPORT.api(
            harness.page,
            "GET",
            f"/api/browser-aside/frame?generation={generation + 1}",
        )
        assert status == 409
        assert body["error"] == {
            "code": "stale_browser_generation",
            "message": "Requested browser generation is stale.",
        }


def test_reconnect_recovers_current_browser_state() -> None:
    with SUPPORT.browser_harness() as harness:
        harness.page.locator("#browser-aside-toggle").click()
        url = harness.page.locator("#browser-aside-url")
        url.fill(harness.fixture_url)
        url.press("Enter")
        canvas = harness.page.locator("#browser-aside-canvas")
        harness.module.expect(canvas).to_have_attribute(
            "data-frame-ready", "true"
        )
        before = SUPPORT.status(harness.page)

        _ = harness.page.goto(harness.web_url)
        harness.page.locator("#browser-aside-toggle").click()
        restored = harness.page.locator("#browser-aside-canvas")
        harness.module.expect(restored).to_have_attribute(
            "data-frame-ready", "true"
        )
        after = SUPPORT.status(harness.page)
        assert after["browser_session_id"] == before["browser_session_id"]
        assert restored.get_attribute(
            "data-frame-digest"
        ) == before["frame_digest"]
