"""Web tools: search for URLs, and fetch one as readable text. No dependencies.

``web_fetch`` reduces HTML with the standard-library ``html.parser``; script
and style content is dropped. Deliberately simple — for heavy scraping, write
a skill that shells out to a dedicated tool.

``web_search`` closes the gap that made the research skills guess at URLs. It
calls two independent, non-commercial indexes that answer plain HTTP with
JSON: **Marginalia** first, **Mwmbl** as a fallback. Both were chosen for one
reason above all — the user has to do nothing. No account, no API key, no card,
no service to run, and no rule bent: these are first-party APIs their operators
publish and invite you to call.

The honest cost is coverage. Both index the non-commercial web, so a question
about asyncio semantics is answered well and a question about today's prices is
not answered at all. That trade is stated in the tool description so the model
knows when an empty result means "not indexed" rather than "does not exist".

Marginalia results are licensed CC-BY-NC-SA 4.0; the attribution rides along in
the output so it reaches whatever the model writes next.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote, urlparse, urlsplit

from .. import __version__
from ..egress import record_tool_receipt
from ..egress_scan import EgressScanError, inspect_payload
from ..httpguard import (
    GuardedRedirectHandler,
    is_public_ip,
    pinned_opener,
)
from .web_document import (
    ContentDecodingError,
    decode_http_body,
    extract_document,
)

from ._types import Tool, ToolContext, ToolResult

MAX_TEXT = 40_000     # historical visible cap; spill.py now applies the limit
# Identify as ourselves, at the real package version. This line used to
# carry the upstream hermes-agent repository URL, which attributed every
# outbound birkin request to another project in the operator's logs.
USER_AGENT = f"birkin/{__version__}"

# Search backends. Hosts are constants so the model never influences them.
MARGINALIA_URL = "https://api2.marginalia-search.com/search"
MWMBL_URL = "https://api.mwmbl.org/api/v1/search/"
MARGINALIA_LICENSE = "CC-BY-NC-SA 4.0"
MARGINALIA_PUBLIC_KEY = "public"   # the key its operator publishes for anyone
SEARCH_TIMEOUT = 10   # a lookup, not a page read: fail into the fallback fast
MAX_RESULTS = 20
_GuardedRedirectHandler = GuardedRedirectHandler


def _is_blocked_literal_url(url: str) -> bool:
    """Reject malformed URLs and unsafe literal addresses without DNS."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return True
        host = parsed.hostname.lower()
        if host == "localhost" or host.endswith(".localhost"):
            return True
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return False
        return not is_public_ip(str(ip))
    except (ValueError, UnicodeError):
        return True


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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _inspect_outgoing_request(
    value: str,
    ctx: ToolContext | None,
) -> ToolResult | None:
    from ._types import ToolResult
    if ctx is None:
        return None
    settings = ctx.cfg.get("egress")
    if (not isinstance(settings, dict)
            or settings.get("enabled") is not True
            or settings.get("enforced") is not True):
        return None
    try:
        inspect_payload(value, None, ctx.cfg)
    except EgressScanError as exc:
        return ToolResult(f"Refused: outgoing request {exc}", is_error=True)
    return None


def _web_fetch(
    inp: dict[str, Any],
    ctx: ToolContext | None,
) -> ToolResult:
    from ._types import ToolResult
    url = inp.get("url", "").strip()
    if not url:
        return ToolResult("Missing url", is_error=True)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    inspection = _inspect_outgoing_request(url, ctx)
    if inspection is not None:
        return inspection
    if _is_blocked_literal_url(url):
        return ToolResult(
            "Refused: that URL targets a local/internal/reserved address "
            "(SSRF guard).", is_error=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = pinned_opener()
    receipt_id = record_tool_receipt(
        ctx.cfg if ctx is not None else {},
        operation="web_fetch",
        outcome="prepared",
    )
    try:
        with opener.open(req, timeout=30) as resp:
            http_status = getattr(resp, "status", None)
            ctype = resp.headers.get("Content-Type", "")
            content_encoding = resp.headers.get("Content-Encoding", "")
            last_modified = resp.headers.get("Last-Modified")
            final_url = (
                resp.geturl()
                if callable(getattr(resp, "geturl", None))
                else url
            )
            raw = resp.read(2_000_000)
    except (OSError, ValueError) as exc:
        record_tool_receipt(
            ctx.cfg if ctx is not None else {},
            operation="web_fetch",
            outcome="failed",
            receipt_id=receipt_id,
        )
        return ToolResult(f"Fetch failed: {exc}", is_error=True)
    record_tool_receipt(
        ctx.cfg if ctx is not None else {},
        operation="web_fetch",
        outcome="sent",
        receipt_id=receipt_id,
        byte_count=len(raw),
        http_status=http_status if isinstance(http_status, int) else None,
    )

    try:
        body = decode_http_body(raw, content_encoding).decode(
            "utf-8", "replace"
        )
    except ContentDecodingError as exc:
        return ToolResult(f"Fetch failed: {exc}", is_error=True)
    published_at: str | None = None
    modified_at: str | None = None
    if "html" in ctype.lower() or body.lstrip()[:1] == "<":
        document = extract_document(body)
        text = document.text
        published_at = document.published_at
        modified_at = document.modified_at
    else:
        text = body
    # No slicing here: the 2MB read above already bounds memory, and
    # tools/spill.py saves the whole page before capping what the model sees.
    metadata = [
        "# Source",
        f"URL: {final_url}",
        f"Retrieved-At: {_utc_now().isoformat(timespec='seconds')}",
        f"Published-At: {published_at or 'unavailable'}",
        f"Modified-At: {modified_at or 'unavailable'}",
        f"HTTP-Last-Modified: {last_modified or 'unavailable'}",
    ]
    return ToolResult("\n".join(metadata) + f"\n\n# Content\n\n{text}")


# -- search ----------------------------------------------------------------

def _get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    """One GET, JSON out. Uses the same guarded opener as web_fetch.

    The host is a constant, so there is nothing to SSRF-check up front — but a
    hijacked or misconfigured redirect off it still must not reach an internal
    address, and that handler is already written.
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    opener = pinned_opener()
    with opener.open(req, timeout=SEARCH_TIMEOUT) as resp:
        return json.loads(resp.read(2_000_000).decode("utf-8", "replace"))


class _SearchReceiptError(RuntimeError):
    pass


def _search_attempt(
    cfg: dict[str, Any],
    provider: str,
    search: Callable[[], list[dict[str, str]]],
) -> list[dict[str, str]]:
    try:
        receipt_id = record_tool_receipt(
            cfg,
            operation="web_search",
            outcome="prepared",
            provider=provider,
        )
    except OSError as exc:
        raise _SearchReceiptError from exc
    try:
        results = search()
    except Exception:
        try:
            record_tool_receipt(
                cfg,
                operation="web_search",
                outcome="failed",
                receipt_id=receipt_id,
                provider=provider,
            )
        except OSError as receipt_exc:
            raise _SearchReceiptError from receipt_exc
        raise
    try:
        record_tool_receipt(
            cfg,
            operation="web_search",
            outcome="sent",
            receipt_id=receipt_id,
            provider=provider,
        )
    except OSError as exc:
        raise _SearchReceiptError from exc
    return results


def _marginalia(query: str, count: int, cfg: dict[str, Any]) -> list[dict[str, str]]:
    key = (os.environ.get("MARGINALIA_API_KEY")
           or (cfg or {}).get("marginalia_api_key")
           or MARGINALIA_PUBLIC_KEY)
    url = f"{MARGINALIA_URL}?query={quote(query)}&count={int(count)}"
    data = _get_json(url, {"API-Key": str(key)})
    out = []
    for r in (data or {}).get("results", []):
        if isinstance(r, dict) and r.get("url"):
            out.append({"url": r["url"], "title": r.get("title") or "",
                        "snippet": r.get("description") or ""})
    return out


def _mwmbl(query: str, count: int) -> list[dict[str, str]]:
    """Fallback. Returns a bare array, and its title/extract are segment lists
    (the shape that lets a UI bold query terms) rather than strings."""
    data = _get_json(f"{MWMBL_URL}?s={quote(query)}")
    out = []
    for r in (data or [])[:count]:
        if not isinstance(r, dict) or not r.get("url"):
            continue
        out.append({"url": r["url"],
                    "title": _segments(r.get("title")),
                    "snippet": _segments(r.get("extract"))})
    return out


def _segments(value: Any) -> str:
    if isinstance(value, list):
        return "".join(str(s.get("value", "")) for s in value
                       if isinstance(s, dict)).strip()
    return str(value or "").strip()


def _render(results: list[dict[str, str]], source: str, license_note: str = "") -> str:
    lines = [
        f"# {len(results)} result(s) — {source}",
        f"Retrieved-At: {_utc_now().isoformat(timespec='seconds')}",
        ("_Search snippets are discovery only; source publication/update date "
        "unavailable. Open the exact URL with web_fetch before citing it._"),
    ]
    if license_note:
        lines.append(f"_Results licensed {license_note}_")
    for r in results:
        lines.append("")
        lines.append(f"## {r['title'] or r['url']}")
        lines.append(r["url"])
        if r["snippet"]:
            lines.append(r["snippet"])
    return "\n".join(lines)


def _web_search(
    inp: dict[str, Any],
    ctx: ToolContext | None,
) -> ToolResult:
    from ._types import ToolResult
    query = str(inp.get("query", "")).strip()
    if not query:
        return ToolResult("Missing query", is_error=True)
    inspection = _inspect_outgoing_request(query, ctx)
    if inspection is not None:
        return inspection
    count = max(1, min(MAX_RESULTS, int(inp.get("count") or 5)))
    cfg = getattr(ctx, "cfg", None) or {}

    tried: list[str] = []
    try:
        hits = _search_attempt(
            cfg,
            "marginalia",
            lambda: _marginalia(query, count, cfg),
        )
        if hits:
            return ToolResult(_render(hits, "Marginalia", MARGINALIA_LICENSE))
        tried.append("Marginalia: no results")
    except _SearchReceiptError:
        return ToolResult(
            "Web search blocked: receipt storage unavailable",
            is_error=True,
        )
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        # 503 here is the shared public key's rate limit. Do NOT retry or back
        # off: that bucket is shared with every other birkin user, so a retry
        # loop degrades it for all of them. Fall through instead.
        tried.append(f"Marginalia: {exc}")

    try:
        hits = _search_attempt(
            cfg,
            "mwmbl",
            lambda: _mwmbl(query, count),
        )
        if hits:
            return ToolResult(_render(hits, "Mwmbl"))
        tried.append("Mwmbl: no results")
    except _SearchReceiptError:
        return ToolResult(
            "Web search blocked: receipt storage unavailable",
            is_error=True,
        )
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        tried.append(f"Mwmbl: {exc}")

    return ToolResult(
        "No results. " + "; ".join(tried) + ". These indexes cover the "
        "non-commercial web (documentation, blogs, forums) and genuinely may "
        "not have this. Try different terms, or web_fetch a URL you already "
        "know.", is_error=True)


def tools() -> list[Tool]:
    return [
        Tool(
            name="web_fetch",
            description="Fetch an exact URL and return readable text plus "
                        "source metadata: final URL, retrieval time, and any "
                        "publication/update dates exposed by the page or HTTP "
                        "headers. Use for documentation, articles, and pages.",
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            fn=_web_fetch,
        ),
        Tool(
            name="web_search",
            description=(
                "Search the web and return result URLs with titles and "
                "snippets. Search snippets are discovery only and do not "
                "provide a reliable publication/update date; open the exact "
                "source URL with web_fetch before citing it. The indexes "
                "(Marginalia, then Mwmbl) are "
                "independent and non-commercial: strong on documentation, "
                "blogs, forums and technical writing; weak on news, shopping "
                "and local queries — an empty result there often means "
                "'not indexed' rather than 'does not exist'. Follow up with "
                "web_fetch on a returned URL to read the page."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "Search terms."},
                    "count": {"type": "integer", "minimum": 1,
                              "maximum": MAX_RESULTS, "default": 5},
                },
                "required": ["query"],
            },
            fn=_web_search,
        ),
    ]
