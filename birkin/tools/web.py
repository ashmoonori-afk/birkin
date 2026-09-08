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
import hashlib
import json
import os
import re
import socket
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote, unquote, urljoin, urlparse, urlsplit

from .. import __version__
from ..egress import record_tool_receipt
from ..egress_scan import EgressScanError, inspect_payload
from ..httpguard import (
    GuardedRedirectHandler,
    is_public_ip,
    pinned_opener,
)
from ..office.safe_xml import DefusedXmlException, ElementTree as ET
from .web_document import (
    ContentDecodingError,
    decode_http_body,
    extract_response,
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
BING_RSS_URL = "https://www.bing.com/search"
MAX_BING_CANDIDATES = 100
_SEARCH_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does",
    "for", "from", "how", "in", "is", "it", "of", "on", "or", "the", "to",
    "was", "what", "when", "where", "which", "who", "why", "with",
    "html", "htm", "txt", "www",
})
MARGINALIA_LICENSE = "CC-BY-NC-SA 4.0"
MARGINALIA_PUBLIC_KEY = "public"   # the key its operator publishes for anyone
SEARCH_TIMEOUT = 10   # a lookup, not a page read: fail into the fallback fast
MAX_RESULTS = 20
MAX_RESPONSE_BYTES = 2_000_000
MAX_DOCUMENT_LINKS = 512
_GuardedRedirectHandler = GuardedRedirectHandler


def _empty_packet(url: str, status: str, error: str | None, attempts: list[dict[str, object]]) -> dict[str, object]:
    return {
        "requested_url": url, "final_url": None, "retrieved_at": None,
        "published_at": None, "modified_at": None, "content_sha256": None,
        "text": "", "status": status, "truncated": False, "error": error,
        "attempts": attempts, "links": [],
    }


def research_fetch(url: str, ctx: ToolContext | None) -> dict[str, object]:
    return _research_fetch(url, ctx, allow_fallback=True)


def _https_canonical_hint(requested: str, error: urllib.error.HTTPError) -> str | None:
    if error.code not in {301, 302, 307, 308}:
        return None
    location = error.headers.get("Location") if error.headers else None
    if not isinstance(location, str):
        return None
    try:
        source, target = urlsplit(requested), urlsplit(location)
        if (
            target.scheme != "http"
            or not target.hostname
            or target.username is not None
            or target.password is not None
            or target.hostname.casefold() != (source.hostname or "").casefold()
            or target.port != source.port
        ):
            return None
        candidate = target._replace(scheme="https", fragment="").geturl()
    except (UnicodeError, ValueError):
        return None
    return None if _is_blocked_literal_url(candidate) else candidate


def _same_https_origin(first: str, second: object) -> bool:
    try:
        left, right = urlsplit(first), urlsplit(second) if isinstance(second, str) else None
        return bool(
            right
            and right.scheme == "https"
            and right.hostname
            and right.username is None
            and right.password is None
            and right.hostname.casefold() == (left.hostname or "").casefold()
            and right.port == left.port
        )
    except (UnicodeError, ValueError):
        return False


def _research_fetch(url: str, ctx: ToolContext | None, *, allow_fallback: bool) -> dict[str, object]:
    requested = str(url).strip()
    if not requested:
        return _empty_packet(requested, "invalid_response", "Missing url", [])
    if not requested.startswith(("http://", "https://")):
        requested = "https://" + requested
    inspection = _inspect_outgoing_request(requested, ctx)
    if inspection is not None:
        return _empty_packet(requested, "blocked", str(inspection.content), [])
    if _is_blocked_literal_url(requested):
        return _empty_packet(requested, "blocked", "SSRF guard refused the URL", [])
    attempt: dict[str, object] = {"url": requested, "status": "prepared", "error": None}
    attempts = [attempt]
    try:
        receipt_id = record_tool_receipt(ctx.cfg if ctx is not None else {}, operation="web_fetch", outcome="prepared")
    except OSError as exc:
        attempt.update(status="blocked", error=str(exc))
        return _empty_packet(requested, "blocked", "receipt storage unavailable", attempts)
    try:
        with pinned_opener().open(urllib.request.Request(requested, headers={"User-Agent": USER_AGENT}), timeout=30) as response:
            http_status = getattr(response, "status", None)
            content_type = response.headers.get("Content-Type", "")
            encoding = response.headers.get("Content-Encoding", "")
            last_modified = response.headers.get("Last-Modified")
            final_url = response.geturl() if callable(getattr(response, "geturl", None)) else requested
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        attempt.update(status="http_error", error=f"HTTP {exc.code}")
        canonical = _https_canonical_hint(requested, exc) if allow_fallback else None
        try:
            record_tool_receipt(ctx.cfg if ctx is not None else {}, operation="web_fetch", outcome="failed", receipt_id=receipt_id, http_status=exc.code)
        finally:
            if exc.fp is not None:
                exc.close()
        if canonical:
            recovered = _research_fetch(canonical, ctx, allow_fallback=False)
            combined_attempts = attempts + recovered["attempts"]
            if recovered["status"] == "ok" and not _same_https_origin(
                requested, recovered.get("final_url"),
            ):
                return _empty_packet(
                    requested, "blocked", "canonical recovery left original origin",
                    combined_attempts,
                )
            recovered["requested_url"] = requested
            recovered["attempts"] = combined_attempts
            return recovered
        return _empty_packet(requested, "http_error", f"HTTP {exc.code}", attempts)
    except (OSError, ValueError) as exc:
        attempt.update(status="network_error", error=str(exc))
        record_tool_receipt(ctx.cfg if ctx is not None else {}, operation="web_fetch", outcome="failed", receipt_id=receipt_id)
        return _empty_packet(requested, "network_error", str(exc), attempts)
    record_tool_receipt(
        ctx.cfg if ctx is not None else {}, operation="web_fetch", outcome="sent", receipt_id=receipt_id,
        byte_count=len(raw), http_status=http_status if isinstance(http_status, int) else None,
    )
    retrieved = _utc_now().isoformat(timespec="seconds")
    attempt["http_last_modified"] = last_modified
    if len(raw) > MAX_RESPONSE_BYTES:
        attempt.update(status="too_large", error="response exceeded 2000000 bytes")
        packet = _empty_packet(requested, "too_large", "response exceeded 2000000 bytes", attempts)
        packet.update(final_url=final_url, retrieved_at=retrieved, truncated=True)
        return packet
    try:
        decoded = decode_http_body(raw, encoding)
        document = extract_response(decoded, content_type)
    except ContentDecodingError as exc:
        status = "unsupported" if "unavailable" in str(exc) else "invalid_response"
        attempt.update(status=status, error=str(exc))
        packet = _empty_packet(requested, status, str(exc), attempts)
        packet.update(final_url=final_url, retrieved_at=retrieved)
        return packet
    text = document.text.strip()
    suspicious = text.casefold()
    blocked_markers = ("enable javascript", "verify you are human", "access denied", "sign in to continue", "로그인 후")
    status = "blocked" if len(text) <= 500 and any(marker in suspicious for marker in blocked_markers) else "ok" if text else "empty"
    error = "page returned a login, challenge, or JavaScript gate" if status == "blocked" else "no readable content" if status == "empty" else None
    attempt.update(status=status, error=error)
    packet = {
        "requested_url": requested, "final_url": final_url, "retrieved_at": retrieved,
        "published_at": document.published_at, "modified_at": document.modified_at or last_modified,
        "content_sha256": hashlib.sha256(decoded).hexdigest(), "text": text,
        "status": status, "truncated": False, "error": error, "attempts": attempts,
        "links": _document_links(document.links, final_url),
    }
    if allow_fallback and status in {"blocked", "empty"} and document.alternate_urls:
        alternate = urljoin(final_url, document.alternate_urls[0])
        fallback = _research_fetch(alternate, ctx, allow_fallback=False)
        packet["attempts"] = attempts + fallback["attempts"]
        if fallback["status"] == "ok":
            fallback["requested_url"] = requested
            fallback["attempts"] = packet["attempts"]
            return fallback
    return packet


def _document_links(
    links: tuple[tuple[str, str], ...],
    final_url: str,
) -> list[dict[str, str]]:
    base = urlsplit(final_url)._replace(fragment="").geturl()
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, text in links:
        try:
            resolved = urlsplit(urljoin(final_url, href))._replace(fragment="")
            url = resolved.geturl()
        except (UnicodeError, ValueError):
            continue
        if (
            resolved.scheme != "https"
            or not resolved.hostname
            or resolved.username is not None
            or resolved.password is not None
            or len(url) > 2048
            or url == base
            or url in seen
            or _is_blocked_literal_url(url)
        ):
            continue
        seen.add(url)
        found.append({"url": url, "text": " ".join(text.split())[:256]})
        if len(found) >= MAX_DOCUMENT_LINKS:
            break
    return found


def _explicit_https_url(query: str) -> str | None:
    match = re.search(r'https://[^\s<>"]+', query)
    if not match:
        return None
    url = match.group(0)
    if not url.isascii():
        return None
    quoted = (
        match.start() > 0
        and query[match.start() - 1] in {'"', "'"}
        and ((match.end() < len(query) and query[match.end()] == '"')
             or url.endswith("'"))
    )
    if quoted and url.endswith("'"):
        url = url[:-1]
    while url.endswith(")") and url.count("(") < url.count(")"):
        url = url[:-1]
    while url.endswith("]") and url.count("[") < url.count("]"):
        url = url[:-1]
    return url or None


def _matches_site(url: object, required_host: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").casefold() if isinstance(url, str) else ""
    except (UnicodeError, ValueError):
        return False
    return host == required_host or host.endswith("." + required_host)


def research_search(query: str, count: int, ctx: ToolContext) -> dict[str, object]:
    normalized = str(query).strip()
    if not normalized:
        return {"query": normalized, "results": [], "status": "error"}
    inspection = _inspect_outgoing_request(normalized, ctx)
    if inspection is not None:
        return {"query": normalized, "results": [], "status": "error"}
    bounded = max(1, min(MAX_RESULTS, int(count)))
    site = re.search(r"(?:^|\s)site:([A-Za-z0-9.-]+)", normalized)
    required_host = site.group(1).casefold() if site else None
    site_path = re.search(r"(?:^|\s)site:([A-Za-z0-9.-]+)(/[^\s]*)", normalized)
    query_url = (
        f"https://{site_path.group(1)}{site_path.group(2)}"
        if site_path else _explicit_https_url(normalized)
    )
    cfg = ctx.cfg
    failures: list[str] = []
    attempts: list[dict[str, str]] = []
    for provider, search in (
        ("marginalia", lambda: _marginalia(normalized, bounded, cfg)),
        ("mwmbl", lambda: _mwmbl(normalized, bounded)),
        ("bing-rss", lambda: _bing_rss(normalized, bounded)),
    ):
        try:
            hits = _search_attempt(cfg, provider, search)
        except _SearchReceiptError:
            return {"query": normalized, "results": [], "status": "error"}
        except urllib.error.HTTPError as exc:
            status = "rate_limited" if exc.code == 429 else "service_unavailable" if exc.code == 503 else "error"
            failures.append(status)
            attempts.append({"backend": provider, "status": status})
            continue
        except (TimeoutError, socket.timeout):
            failures.append("timeout")
            attempts.append({"backend": provider, "status": "timeout"})
            continue
        except (AttributeError, OSError, TypeError, ValueError):
            failures.append("error")
            attempts.append({"backend": provider, "status": "error"})
            continue
        if required_host:
            hits = [
                hit for hit in hits
                if isinstance(hit, dict)
                and _matches_site(hit.get("url"), required_host)
            ]
        hits = [
            hit for hit in hits
            if isinstance(hit, dict)
            and _search_result_relevant(
                normalized, hit, site_bound=required_host is not None,
            )
        ]
        if hits:
            attempts.append({"backend": provider, "status": "ok"})
            results = []
            if query_url and not _is_blocked_literal_url(query_url):
                results.append({
                    "title": urlsplit(query_url).path.rsplit("/", 1)[-1],
                    "url": query_url, "snippet": "", "published_at": None,
                    "backend": None, "discovery_method": "query_url",
                    "attempt_statuses": list(attempts),
                })
            results.extend(
                {
                    "title": hit.get("title", ""), "url": hit["url"],
                    "snippet": hit.get("snippet", ""),
                    "published_at": hit.get("published_at") or None,
                    "backend": provider, "discovery_method": "search_backend",
                    "attempt_statuses": list(attempts),
                }
                for hit in hits
                if hit["url"] != query_url
            )
            return {
                "query": normalized,
                "results": results[:bounded],
                "status": "ok",
            }
        attempts.append({"backend": provider, "status": "no_results"})
    status = next((item for item in ("rate_limited", "service_unavailable", "timeout", "error") if item in failures), "no_results")
    results = []
    if query_url and not _is_blocked_literal_url(query_url):
        results.append({
            "title": urlsplit(query_url).path.rsplit("/", 1)[-1],
            "url": query_url, "snippet": "", "published_at": None,
            "backend": None, "discovery_method": "query_url",
            "attempt_statuses": list(attempts),
        })
    return {"query": normalized, "results": results, "status": status}


def _is_blocked_literal_url(url: str) -> bool:
    """Reject malformed URLs and unsafe literal addresses without DNS."""
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
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
    requested = inp.get("url", "").strip()
    if not requested:
        return ToolResult("Missing url", is_error=True)
    packet = research_fetch(requested, ctx)
    if packet["status"] != "ok":
        prefix = "Refused" if packet["status"] == "blocked" else "Fetch failed"
        return ToolResult(f"{prefix}: {packet['error']}", is_error=True)
    attempts = packet["attempts"]
    last_modified = (
        attempts[-1].get("http_last_modified")
        if isinstance(attempts, list) and attempts and isinstance(attempts[-1], dict)
        else None
    )
    metadata = [
        "# Source",
        f"URL: {packet['final_url']}",
        f"Retrieved-At: {packet['retrieved_at']}",
        f"Published-At: {packet['published_at'] or 'unavailable'}",
        f"Modified-At: {packet['modified_at'] or 'unavailable'}",
        f"HTTP-Last-Modified: {last_modified or 'unavailable'}",
    ]
    return ToolResult("\n".join(metadata) + f"\n\n# Content\n\n{packet['text']}")


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


def _bing_rss(query: str, count: int) -> list[dict[str, str]]:
    """Public RSS search response; no browser session, cookie, or credential."""
    site = re.search(r"(?:^|\s)site:([A-Za-z0-9.-]+)", query)
    required_host = site.group(1).casefold() if site else None
    searched = re.sub(r"(?:^|\s)site:[^\s]+", " ", query).strip()
    if required_host:
        searched = f"{required_host} {searched}".strip()
    url = f"{BING_RSS_URL}?format=rss&q={quote(searched)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with pinned_opener().open(request, timeout=SEARCH_TIMEOUT) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Bing RSS response exceeded 2000000 bytes")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Bing RSS response contained a DTD or entity declaration")
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise ValueError("Bing RSS response was malformed XML") from exc
    results: list[dict[str, str]] = []
    for item in root.findall("./channel/item")[:MAX_BING_CANDIDATES]:
        if len(results) >= count:
            break
        link = (item.findtext("link") or "").strip()
        if not link or _is_blocked_literal_url(link):
            continue
        host = (urlsplit(link).hostname or "").casefold()
        if required_host and host != required_host and not host.endswith("." + required_host):
            continue
        result = {
            "url": link,
            "title": (item.findtext("title") or "").strip(),
            "snippet": (item.findtext("description") or "").strip(),
            "published_at": (item.findtext("pubDate") or "").strip(),
        }
        if _search_result_relevant(
            query, result, site_bound=required_host is not None,
        ):
            results.append(result)
    return results


def _informative_search_tokens(value: str) -> set[str]:
    without_site = re.sub(r"(?:^|\s)site:[^\s]+", " ", value.casefold())
    return {
        token
        for token in re.findall(r"[^\W_]+", without_site, flags=re.UNICODE)
        if len(token) > 1 and not token.isdigit() and token not in _SEARCH_STOPWORDS
    }


def _search_result_relevant(
    query: str,
    result: Mapping[str, Any],
    *,
    site_bound: bool,
) -> bool:
    # ponytail: lexical overlap can miss synonyms; add semantic ranking only
    # after a measured search corpus justifies that extra machinery.
    title, snippet, url = (
        result.get("title", ""), result.get("snippet", ""), result.get("url")
    )
    if not all(isinstance(value, str) for value in (title, snippet, url)):
        return False
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname
                or _is_blocked_literal_url(url)):
            return False
        host_tokens = _informative_search_tokens(parsed.hostname)
        searchable = " ".join((title, snippet, unquote(parsed.path),
                               unquote(parsed.query)))
    except (UnicodeError, ValueError):
        return False
    original_wanted = _informative_search_tokens(query)
    if not original_wanted:
        return site_bound
    wanted = original_wanted - host_tokens or original_wanted
    found = _informative_search_tokens(searchable)
    minimum = 1 if len(wanted) == 1 else 2
    return len(wanted & found) >= minimum


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
