"""Web tool: fetch a URL and return readable text (no external dependencies).

HTML is reduced to text with the standard-library ``html.parser``; script and
style content is dropped. This is deliberately simple — for heavy scraping,
write a skill that shells out to a dedicated tool.
"""

from __future__ import annotations

import urllib.request
from html.parser import HTMLParser
from typing import Any

from . import Tool, ToolContext, ToolResult

MAX_TEXT = 40_000
USER_AGENT = "birkin/0.1 (+https://github.com/NousResearch/hermes-agent)"


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "head"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self.parts.append(text)


def _web_fetch(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
    url = inp.get("url", "").strip()
    if not url:
        return ToolResult("Missing url", is_error=True)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read(2_000_000)
    except Exception as exc:
        return ToolResult(f"Fetch failed: {exc}", is_error=True)

    body = raw.decode("utf-8", "replace")
    if "html" in ctype.lower() or body.lstrip()[:1] == "<":
        parser = _TextExtractor()
        parser.feed(body)
        text = "\n".join(parser.parts)
    else:
        text = body
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + "\n[truncated]"
    return ToolResult(f"# {url}\n\n{text}")


def tools() -> list[Tool]:
    return [
        Tool(
            name="web_fetch",
            description="Fetch a URL and return its readable text content. "
                        "Use for documentation, articles, and pages.",
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            fn=_web_fetch,
        ),
    ]
