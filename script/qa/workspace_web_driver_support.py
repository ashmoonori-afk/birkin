"""Layout assertions shared by the real-Chrome workspace driver."""

from __future__ import annotations

from typing import cast

from playwright.sync_api import Page

CONNECTED = """() => document.querySelector(
  '[data-testid="workspace-connection"]'
).dataset.state === 'connected'"""
PANEL_OPEN = """() => document.querySelector(
  '[data-testid="workspace-shell"]'
).dataset.panelOpen === 'true'"""
_TOUCH_TARGET_SIZES = """(nodes) => nodes.map((node) => {
  const box = node.getBoundingClientRect();
  return [box.width, box.height];
})"""


def assert_layout(page: Page) -> None:
    overflow_value = cast(
        object,
        page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        ),
    )
    if not isinstance(overflow_value, (int, float)):
        raise TypeError("browser overflow measurement must be numeric")
    if overflow_value > 0:
        raise AssertionError(f"horizontal overflow: {overflow_value}px")


def assert_tablet_overflow(page: Page) -> None:
    value = cast(
        object,
        page.locator('[data-testid="workspace-panel-tabs"]').evaluate(
            "(node) => [node.scrollLeft, node.clientWidth, node.scrollWidth]"
        ),
    )
    if not isinstance(value, list):
        raise TypeError(f"tablet panel overflow is not a list: {value}")
    values = cast(list[object], value)
    if len(values) != 3 or not all(
        isinstance(item, (int, float)) for item in values
    ):
        raise AssertionError(f"tablet panel overflow values are invalid: {values}")
    scroll_left, client_width, scroll_width = cast(list[float], values)
    if scroll_width <= client_width:
        raise AssertionError(f"tablet panel overflow was not exposed: {values}")
    _ = page.locator("#panel-more").click()
    after = cast(
        object,
        page.locator('[data-testid="workspace-panel-tabs"]').evaluate(
            "(node) => node.scrollLeft"
        ),
    )
    if not isinstance(after, (int, float)) or after <= scroll_left:
        raise AssertionError(f"panel overflow control did not scroll tabs: {after}")


def assert_open_mobile_drawer(page: Page) -> None:
    _ = page.wait_for_function(PANEL_OPEN)
    if not page.locator(
        '[data-testid="workspace-mobile-back"]'
    ).is_visible():
        raise AssertionError("mobile back is hidden in the open drawer")
    transition_result = cast(
        object,
        page.locator(".context-panel").evaluate(
            """(node) => new Promise((resolve) => {
              const transform = getComputedStyle(node).transform;
              if (transform === 'none' || transform.endsWith(', 0)')) {
                resolve();
                return;
              }
              node.addEventListener('transitionend', resolve, {once: true});
            })"""
        ),
    )
    if transition_result is not None and not isinstance(transition_result, dict):
        raise TypeError(f"unexpected transition result: {transition_result}")
    assert_layout(page)
    sizes = cast(
        list[list[float]],
        page.locator(
            ".panel-tab:visible, .panel-more:visible, .action:visible, "
            + "#lens-toggle:visible"
        ).evaluate_all(_TOUCH_TARGET_SIZES),
    )
    if any(min(width, height) < 43.5 for width, height in sizes):
        raise AssertionError(f"mobile touch target below 44px: {sizes}")
    drawer_box = page.locator(".context-panel").bounding_box()
    composer_box = page.locator("#workspace-composer").bounding_box()
    if drawer_box is None or composer_box is None:
        raise AssertionError("mobile drawer or composer is not visible")
    if drawer_box["y"] + drawer_box["height"] > composer_box["y"]:
        raise AssertionError(
            f"mobile drawer occludes composer: {drawer_box}, {composer_box}"
        )
    background = cast(
        object,
        page.locator(".context-panel").evaluate(
            "(node) => getComputedStyle(node).backgroundColor"
        ),
    )
    if not isinstance(background, str) or background.startswith("rgba"):
        raise AssertionError(f"mobile drawer is not opaque: {background}")


def assert_closed_mobile_drawer(page: Page, viewport_height: int) -> None:
    assert_layout(page)
    composer_box = page.locator("#workspace-composer").bounding_box()
    if (
        composer_box is None
        or composer_box["y"] + composer_box["height"] > viewport_height
    ):
        raise AssertionError(f"mobile composer left viewport: {composer_box}")
    drawer_box = page.locator(".context-panel").bounding_box()
    if drawer_box is None or drawer_box["y"] < viewport_height:
        raise AssertionError(
            f"closed mobile drawer remains in viewport: {drawer_box}"
        )
