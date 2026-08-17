from __future__ import annotations

from pathlib import Path

import pytest

from birkin import store
from tests import native_browser_aside_support as SUPPORT

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(
        not SUPPORT.browser_ready(),
        reason="set BIRKIN_BROWSER_INTEGRATION=1 and install Playwright Chromium",
    ),
]


def test_rejects_non_http_navigation_and_closes_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with SUPPORT.browser_harness() as harness:
        start_status, _ = SUPPORT.api(
            harness.page,
            "POST",
            "/api/browser-aside/session",
            {},
        )
        assert start_status == 201

        denied_status, denied = SUPPORT.api(
            harness.page,
            "POST",
            "/api/browser-aside/navigate",
            {"url": "file:///etc/passwd"},
        )
        assert denied_status == 400
        assert denied["error"] == {
            "code": "unsupported_scheme",
            "message": "Only http and https navigation is allowed.",
        }

        close_status, closed = SUPPORT.api(
            harness.page,
            "DELETE",
            "/api/browser-aside/session",
        )
        assert close_status == 200, closed
        assert closed["closed"] is True
        assert SUPPORT.status(harness.page)["live"] is False

    monkeypatch.setenv("BIRKIN_BROWSER_FORCE_UNAVAILABLE", "1")
    with SUPPORT.browser_harness() as unavailable:
        missing_status, missing = SUPPORT.api(
            unavailable.page,
            "POST",
            "/api/browser-aside/session",
            {},
        )
        assert missing_status == 503
        assert missing["error"] == {
            "code": "browser_unavailable",
            "message": (
                "Install the optional browser dependency and Chromium with "
                "`uv sync --extra browser && uv run playwright install chromium`."
            ),
        }
        unavailable.page.locator("#browser-aside-toggle").click()
        status_node = unavailable.page.locator(
            "#browser-aside-status"
        )
        unavailable.module.expect(status_node).to_have_attribute(
            "data-state",
            "error",
        )
        assert status_node.get_attribute("aria-live") == "assertive"


def test_web_contract_exposes_native_aside_without_iframe() -> None:
    with SUPPORT.browser_harness() as harness:
        assert harness.page.locator("iframe").count() == 0
        for selector in (
            "#browser-aside-toggle",
            "#browser-aside",
            "#browser-aside-url",
            "#browser-aside-canvas",
        ):
            harness.module.expect(
                harness.page.locator(selector)
            ).to_have_count(1)

        harness.module.expect(
            harness.page.locator("#lens")
        ).to_be_visible()

        aside_toggle = harness.page.locator("#browser-aside-toggle")
        aside_toggle.click()
        harness.module.expect(aside_toggle).to_have_attribute(
            "aria-expanded",
            "true",
        )
        harness.page.locator("#browser-aside-url").focus()
        assert harness.page.evaluate(
            "() => document.activeElement.id"
        ) == "browser-aside-url"
        assert harness.page.evaluate(
            """() => document.documentElement.scrollWidth <=
              document.documentElement.clientWidth"""
        ) is True


@pytest.mark.parametrize(
    ("width", "height"),
    ((768, 900), (390, 844)),
)
def test_populated_workspace_stays_bounded_at_responsive_widths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    width: int,
    height: int,
) -> None:
    from birkin import store

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    _ = store.add_pending(
        category="browser",
        title="브라우저 정책 승인",
        description="격리된 Chromium 탐색 검증",
        payload={"target": "https://example.com"},
    )
    with SUPPORT.browser_harness() as harness:
        harness.page.locator("#approval-tab").click()
        item = harness.page.locator(".panel-item")
        harness.module.expect(item).to_have_count(1)
        item.click()
        harness.page.locator("#browser-aside-toggle").click()
        harness.page.set_viewport_size(
            {"width": width, "height": height}
        )
        assert harness.page.evaluate(
            """() => document.documentElement.scrollHeight <=
              document.documentElement.clientHeight"""
        ) is True
        assert harness.page.evaluate(
            """() => document.documentElement.scrollWidth <=
              document.documentElement.clientWidth"""
        ) is True
        bounds = harness.page.evaluate(
            """() => {
              const shell = document.querySelector(
                '#workspace-shell'
              ).getBoundingClientRect();
              const aside = document.querySelector(
                '#browser-aside'
              ).getBoundingClientRect();
              return {
                innerWidth: window.innerWidth,
                shellLeft: shell.left,
                shellRight: shell.right,
                asideLeft: aside.left,
                asideRight: aside.right,
              };
            }"""
        )
        assert isinstance(bounds, dict)
        assert bounds["innerWidth"] == width
        assert bounds["shellLeft"] >= 0
        assert bounds["shellRight"] <= width
        assert bounds["asideLeft"] >= 0
        assert bounds["asideRight"] <= width


def test_mutations_reject_stale_generation_and_control_epoch() -> None:
    with SUPPORT.browser_harness() as harness:
        start_status, started = SUPPORT.api(
            harness.page,
            "POST",
            "/api/browser-aside/session",
            {},
        )
        assert start_status == 201
        generation = started["browser_generation"]
        epoch = started["control_epoch"]
        assert isinstance(generation, int)
        assert isinstance(epoch, int)
        raw = harness.page.evaluate(
            """async ({generation, revision, epoch, url}) => {
              const navigate = await fetch(
                '/api/browser-aside/navigate',
                {
                  method: 'POST',
                  headers: {
                    'Content-Type': 'application/json',
                    'X-Birkin-Browser-Client':
                      window.__birkinTestClient,
                  },
                  body: JSON.stringify({
                    url,
                    browser_generation: generation - 1,
                    browser_revision: revision,
                    control_epoch: epoch,
                    control_sequence: 1,
                  }),
                }
              );
              const close = await fetch(
                '/api/browser-aside/session' +
                  `?generation=${generation}` +
                  `&revision=${revision}` +
                  `&control_epoch=${epoch - 1}` +
                  `&control_sequence=1`,
                {
                  method: 'DELETE',
                  headers: {
                    'X-Birkin-Browser-Client':
                      window.__birkinTestClient,
                  },
                }
              );
              return {
                navigateStatus: navigate.status,
                navigateBody: await navigate.json(),
                closeStatus: close.status,
                closeBody: await close.json(),
              };
            }""",
            {
                "generation": generation,
                "revision": started["browser_revision"],
                "epoch": epoch,
                "url": harness.fixture_url,
            },
        )
        assert isinstance(raw, dict)
        assert raw["navigateStatus"] == 409
        assert raw["closeStatus"] == 409
        assert raw["navigateBody"] == {
            "error": {
                "code": "stale_browser_generation",
                "message": "Browser generation is stale.",
            }
        }
        assert raw["closeBody"] == {
            "error": {
                "code": "stale_control_epoch",
                "message": (
                    "Browser control lease is stale or not owned."
                ),
            }
        }
        assert SUPPORT.status(harness.page)["live"] is True


def test_page_form_submission_is_scanned_and_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    SUPPORT.FixtureHandler.post_count = 0
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
            {"url": harness.fixture_url + "/auto-form"},
        )
        assert navigate_status == 200
        assert SUPPORT.FixtureHandler.post_count == 0
        serialized = repr((
            store.list_pending(),
            (tmp_path / "ledger.jsonl").read_text(
                encoding="utf-8"
            ),
        ))
        assert "PRIVATE-SENTINEL-9911" not in serialized


def test_page_websocket_constructor_is_disabled() -> None:
    with SUPPORT.browser_harness() as harness:
        harness.page.locator("#browser-aside-toggle").click()
        url = harness.page.locator("#browser-aside-url")
        url.fill(harness.fixture_url + "/websocket")
        url.press("Enter")
        canvas = harness.page.locator("#browser-aside-canvas")
        harness.module.expect(canvas).to_have_attribute(
            "data-frame-ready",
            "true",
        )
        assert SUPPORT.colors_match(
            SUPPORT.canvas_color(canvas),
            SUPPORT.WEBSOCKET_BLOCKED_COLOR,
        )
