"""Web tool: fetch a URL and return readable text (no external dependencies).

HTML is reduced to text with the standard-library ``html.parser``; script and
style content is dropped. This is deliberately simple — for heavy scraping,
write a skill that shells out to a dedicated tool.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from . import Tool, ToolContext, ToolResult

MAX_TEXT = 40_000     # historical visible cap; spill.py now applies the limit
USER_AGENT = "birkin/0.1 (+https://github.com/NousResearch/hermes-agent)"


def _is_blocked_url(url: str) -> bool:
    """SSRF guard: refuse loopback / link-local / private / reserved targets.

    Resolves the host (catches DNS-rebinding to an internal IP) and blocks if
    ANY resolved address is non-public. Fails OPEN only for genuinely
    unresolvable public hostnames (those just fail at fetch time anyway).
    """
    host = (urlparse(url).hostname or "").lower()
    if not host or host in ("localhost", "ip6-localhost"):
        return True
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except (socket.gaierror, UnicodeError, ValueError):
        addrs = {host}  # literal IP or unresolvable — check the literal below
    for a in addrs:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            continue
        if (ip.is_loopback or ip.is_link_local or ip.is_private
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return True
    return False


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-run the SSRF guard on every redirect target.

    ``urlopen`` follows 30x automatically, and the default handler does NOT
    re-validate the new location — so a public URL could 302 to
    ``http://169.254.169.254/...`` (cloud metadata) or an internal address and
    bypass the up-front ``_is_blocked_url`` check. Refuse a blocked hop."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        if _is_blocked_url(newurl):
            raise urllib.error.HTTPError(
                newurl, code, "redirect to a local/internal/reserved address "
                "(SSRF guard)", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


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
    if _is_blocked_url(url):
        return ToolResult(
            "Refused: that URL targets a local/internal/reserved address "
            "(SSRF guard).", is_error=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(_GuardedRedirectHandler)
    try:
        with opener.open(req, timeout=30) as resp:
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
    # No slicing here: the 2MB read above already bounds memory, and
    # tools/spill.py saves the whole page before capping what the model sees.
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
