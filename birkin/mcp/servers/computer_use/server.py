"""Computer Use MCP server — exposes browser automation as tools.

Packaged as Birkin Tool instances (not a standalone MCP process)
so they integrate directly with the Agent's tool registry.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from birkin.mcp.servers.computer_use.browser import BrowserSession, is_available
from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec

logger = logging.getLogger(__name__)

# Shared session — created lazily on first tool call
_session: BrowserSession | None = None


async def _get_session() -> BrowserSession:
    global _session
    if _session is None:
        _session = BrowserSession(headless=True)
        await _session.__aenter__()
    return _session


class NavigateTool(Tool):
    """Navigate the browser to a URL."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_navigate",
            description="Navigate the browser to a URL and return the page title.",
            parameters=[ToolParameter(name="url", type="string", description="URL to navigate to")],
            toolset="computer_use",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        if not is_available():
            return ToolOutput(success=False, output="", error="Playwright not installed")
        try:
            session = await _get_session()
            title = await session.navigate(args["url"])
            return ToolOutput(success=True, output=f"Navigated to: {title}")
        except (OSError, RuntimeError, ValueError) as exc:
            return ToolOutput(success=False, output="", error=str(exc))


class ScreenshotTool(Tool):
    """Take a screenshot of the current page."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_screenshot",
            description="Take a PNG screenshot of the current browser page. Returns base64-encoded image.",
            parameters=[],
            toolset="computer_use",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        if not is_available():
            return ToolOutput(success=False, output="", error="Playwright not installed")
        try:
            session = await _get_session()
            png_bytes = await session.screenshot()
            b64 = base64.b64encode(png_bytes).decode()
            return ToolOutput(success=True, output=b64, metadata={"format": "png", "encoding": "base64"})
        except (OSError, RuntimeError) as exc:
            return ToolOutput(success=False, output="", error=str(exc))


class ClickTool(Tool):
    """Click an element on the page."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_click",
            description="Click an element by CSS selector.",
            parameters=[ToolParameter(name="selector", type="string", description="CSS selector")],
            toolset="computer_use",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        if not is_available():
            return ToolOutput(success=False, output="", error="Playwright not installed")
        try:
            session = await _get_session()
            await session.click(args["selector"])
            return ToolOutput(success=True, output=f"Clicked: {args['selector']}")
        except (OSError, RuntimeError) as exc:
            return ToolOutput(success=False, output="", error=str(exc))


class TypeTool(Tool):
    """Type text into an input element."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_type",
            description="Type text into an input element by CSS selector.",
            parameters=[
                ToolParameter(name="selector", type="string", description="CSS selector of input"),
                ToolParameter(name="text", type="string", description="Text to type"),
            ],
            toolset="computer_use",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        if not is_available():
            return ToolOutput(success=False, output="", error="Playwright not installed")
        try:
            session = await _get_session()
            await session.type_text(args["selector"], args["text"])
            return ToolOutput(success=True, output=f"Typed into: {args['selector']}")
        except (OSError, RuntimeError) as exc:
            return ToolOutput(success=False, output="", error=str(exc))


class ExtractTextTool(Tool):
    """Extract text content from the page."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_extract",
            description="Extract text content from an element by CSS selector.",
            parameters=[
                ToolParameter(
                    name="selector",
                    type="string",
                    description="CSS selector (default: body)",
                    required=False,
                    default="body",
                ),
            ],
            toolset="computer_use",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        if not is_available():
            return ToolOutput(success=False, output="", error="Playwright not installed")
        try:
            session = await _get_session()
            text = await session.extract_text(args.get("selector", "body"))
            return ToolOutput(success=True, output=text[:5000])
        except (OSError, RuntimeError) as exc:
            return ToolOutput(success=False, output="", error=str(exc))


class WaitForTool(Tool):
    """Wait for an element to appear on the page."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_wait_for",
            description="Wait for an element to appear by CSS selector.",
            parameters=[
                ToolParameter(name="selector", type="string", description="CSS selector to wait for"),
            ],
            toolset="computer_use",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        if not is_available():
            return ToolOutput(success=False, output="", error="Playwright not installed")
        try:
            session = await _get_session()
            found = await session.wait_for(args["selector"])
            if found:
                return ToolOutput(success=True, output=f"Element found: {args['selector']}")
            return ToolOutput(success=False, output="", error=f"Element not found: {args['selector']}")
        except (OSError, RuntimeError) as exc:
            return ToolOutput(success=False, output="", error=str(exc))


ALL_COMPUTER_USE_TOOLS = [
    NavigateTool,
    ScreenshotTool,
    ClickTool,
    TypeTool,
    ExtractTextTool,
    WaitForTool,
]
