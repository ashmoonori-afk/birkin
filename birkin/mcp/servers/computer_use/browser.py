"""Browser session management using Playwright (optional dependency)."""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Playwright is an optional heavy dependency
_playwright_available = False
try:
    from playwright.async_api import async_playwright  # noqa: F401

    _playwright_available = True
except ImportError:
    pass


def is_available() -> bool:
    """Check if Playwright is installed."""
    return _playwright_available


class BrowserSession:
    """Manages a headless browser session via Playwright.

    Usage::

        async with BrowserSession() as session:
            await session.navigate("https://example.com")
            text = await session.extract_text("body")
            screenshot = await session.screenshot()
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        allowed_domains: Optional[list[str]] = None,
        timeout_ms: int = 30000,
    ) -> None:
        if not _playwright_available:
            raise RuntimeError("Playwright is not installed. Run: pip install playwright && playwright install")
        self._headless = headless
        self._allowed_domains = set(allowed_domains) if allowed_domains else None
        self._timeout_ms = timeout_ms
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    async def __aenter__(self) -> BrowserSession:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self._timeout_ms)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    def _check_domain(self, url: str) -> None:
        """Enforce domain allowlist."""
        if self._allowed_domains is None:
            return
        from urllib.parse import urlparse

        domain = urlparse(url).netloc
        if domain not in self._allowed_domains:
            raise ValueError(f"Domain {domain!r} not in allowlist: {self._allowed_domains}")

    async def navigate(self, url: str) -> str:
        """Navigate to a URL. Returns the page title."""
        self._check_domain(url)
        await self._page.goto(url, wait_until="domcontentloaded")
        return await self._page.title()

    async def screenshot(self) -> bytes:
        """Take a screenshot of the current page."""
        return await self._page.screenshot(type="png")

    async def click(self, selector: str) -> None:
        """Click an element by CSS selector."""
        await self._page.click(selector)

    async def type_text(self, selector: str, text: str) -> None:
        """Type text into an input element."""
        await self._page.fill(selector, text)

    async def extract_text(self, selector: str = "body") -> str:
        """Extract text content from an element."""
        element = await self._page.query_selector(selector)
        if element is None:
            return ""
        return await element.inner_text()

    async def wait_for(self, selector: str, timeout_ms: Optional[int] = None) -> bool:
        """Wait for an element to appear. Returns True if found."""
        try:
            await self._page.wait_for_selector(selector, timeout=timeout_ms or self._timeout_ms)
            return True
        except Exception:
            return False

    async def get_url(self) -> str:
        """Return the current page URL."""
        return self._page.url
