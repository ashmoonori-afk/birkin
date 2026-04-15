"""Web search tool using DuckDuckGo HTML (no API key required)."""

from __future__ import annotations

import html
import re
from typing import Any

import httpx

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec

_DDG_URL = "https://html.duckduckgo.com/html/"
_MAX_RESULTS = 5
_TIMEOUT_SECONDS = 15

# Patterns for extracting result blocks from DuckDuckGo HTML.
_RESULT_BLOCK_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]*)"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    return html.unescape(_TAG_RE.sub("", text)).strip()


def _extract_url(raw_href: str) -> str:
    """DuckDuckGo wraps URLs in a redirect; extract the real destination."""
    # The href often looks like //duckduckgo.com/l/?uddg=https%3A%2F%2F...&rut=...
    match = re.search(r"uddg=([^&]+)", raw_href)
    if match:
        from urllib.parse import unquote

        return unquote(match.group(1))
    # Fallback: return as-is (sometimes it's a direct URL).
    if raw_href.startswith("//"):
        return "https:" + raw_href
    return raw_href


class WebSearchTool(Tool):
    """Search the web using DuckDuckGo HTML (no API key required)."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_search",
            description=(
                "Search the web using DuckDuckGo and return the top results "
                "with title, snippet, and URL. No API key required."
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="The search query.",
                    required=True,
                ),
            ],
            toolset="builtin",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        query = args.get("query", "").strip()
        if not query:
            return ToolOutput(success=False, output="", error="No search query provided.")

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=_TIMEOUT_SECONDS,
            ) as client:
                resp = await client.post(
                    _DDG_URL,
                    data={"q": query},
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                    },
                )
                resp.raise_for_status()
                body = resp.text
        except httpx.HTTPStatusError as exc:
            return ToolOutput(
                success=False,
                output="",
                error=f"DuckDuckGo returned HTTP {exc.response.status_code}.",
            )
        except httpx.TimeoutException:
            return ToolOutput(success=False, output="", error="Search request timed out.")
        except httpx.HTTPError as exc:
            return ToolOutput(success=False, output="", error=f"HTTP error: {exc}")

        # Parse results from HTML.
        link_matches = _RESULT_BLOCK_RE.findall(body)
        snippet_matches = _SNIPPET_RE.findall(body)

        results: list[str] = []
        for i, (raw_href, raw_title) in enumerate(link_matches[:_MAX_RESULTS]):
            title = _strip_tags(raw_title)
            url = _extract_url(raw_href)
            snippet = _strip_tags(snippet_matches[i]) if i < len(snippet_matches) else ""
            results.append(f"{i + 1}. {title}\n   {url}\n   {snippet}")

        if not results:
            return ToolOutput(
                success=True,
                output="No results found.",
                metadata={"result_count": 0},
            )

        output = "\n\n".join(results)
        return ToolOutput(
            success=True,
            output=output,
            metadata={"result_count": len(results)},
        )
