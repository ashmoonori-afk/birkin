from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
import urllib.request
from urllib.parse import urlsplit

import pytest

from birkin.tools import web
from birkin.tools._types import ToolContext


class Response:
    def __init__(self, body: bytes, content_type: str = "text/html") -> None:
        self.body = body
        self.headers = {"Content-Type": content_type}
        self.status = 200

    def __enter__(self) -> "Response":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        pass

    def read(self, size: int) -> bytes:
        return self.body[:size]

    def geturl(self) -> str:
        return "https://example.test/final"


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(cfg={}, client=None, cwd=tmp_path)


def _network(monkeypatch: pytest.MonkeyPatch, response: Response) -> None:
    class Opener:
        def open(self, request: urllib.request.Request, timeout: int) -> Response:
            return response

    monkeypatch.setattr(web, "pinned_opener", lambda: Opener())
    monkeypatch.setattr(web, "record_tool_receipt", lambda *args, **kwargs: "receipt")


def test_research_fetch_returns_structured_html_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _network(monkeypatch, Response(
        b'<html><head><meta property="article:published_time" content="2026-09-01"></head>'
        b"<body><main>Verified public report</main></body></html>",
    ))
    packet = web.research_fetch("https://example.test/report", _ctx(tmp_path))
    assert set(packet) == {
        "requested_url", "final_url", "retrieved_at", "published_at", "modified_at",
        "content_sha256", "text", "status", "truncated", "error", "attempts",
        "links",
    }
    assert packet["status"] == "ok"
    assert packet["published_at"] == "2026-09-01"
    assert packet["text"] == "Verified public report"


def test_research_fetch_resolves_safe_document_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _network(monkeypatch, Response(
        b'<main><a href="../reports/tr15/#forms">Unicode <b>normalization</b></a>'
        b'<a href="https://example.test/final#contents">same page</a>'
        b'<a href="http://example.test/plain">plain HTTP</a>'
        b'<a href="https://user:secret@example.test/private">credentials</a>'
        b'<a href="javascript:alert(1)">script</a>'
        b'<a href="../reports/tr15/#other">duplicate</a></main>',
    ))

    packet = web.research_fetch("https://example.test/start", _ctx(tmp_path))

    assert packet["links"] == [{
        "url": "https://example.test/reports/tr15/",
        "text": "Unicode normalization",
    }]


def test_research_fetch_caps_after_fragment_and_duplicate_filtering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fragments = "".join(
        f'<a href="#section-{index}">section</a>' for index in range(600)
    )
    body = (
        f'<main>{fragments}<a href="/reports/tr15/">UAX 15</a></main>'
    ).encode()
    _network(monkeypatch, Response(body))

    packet = web.research_fetch("https://example.test/start", _ctx(tmp_path))

    assert packet["links"] == [{
        "url": "https://example.test/reports/tr15/", "text": "UAX 15",
    }]


@pytest.mark.parametrize(
    ("body", "content_type", "expected"),
    [
        (json.dumps({"answer": 42}).encode(), "application/json", '"answer": 42'),
        (b"<rss><channel><pubDate>2026-09-01</pubDate><item><title>Public feed</title></item></channel></rss>", "application/rss+xml", "Public feed"),
    ],
)
def test_research_fetch_reads_json_and_rss(
    body: bytes, content_type: str, expected: str,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _network(monkeypatch, Response(body, content_type))
    packet = web.research_fetch("https://example.test/data", _ctx(tmp_path))
    assert packet["status"] == "ok"
    assert expected in packet["text"]


def test_research_fetch_rejects_challenge_and_detects_oversize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _network(monkeypatch, Response(b"<html><body>Verify you are human</body></html>"))
    blocked = web.research_fetch("https://example.test/report", _ctx(tmp_path))
    assert blocked["status"] == "blocked" and blocked["text"]

    _network(monkeypatch, Response(b"x" * (web.MAX_RESPONSE_BYTES + 1), "text/plain"))
    large = web.research_fetch("https://example.test/large", _ctx(tmp_path))
    assert large["status"] == "too_large"
    assert large["truncated"] is True and large["text"] == ""


def test_research_fetch_does_not_block_long_security_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = (
        "<html><body><article><h1>Access control guide</h1>"
        + ("This guide explains why an access denied response should be audited. " * 20)
        + "</article></body></html>"
    ).encode()
    _network(monkeypatch, Response(body))
    packet = web.research_fetch("https://example.test/security", _ctx(tmp_path))
    assert packet["status"] == "ok"
    assert "access denied" in packet["text"].casefold()


def test_research_fetch_rejects_xml_dtd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _network(monkeypatch, Response(
        b'<!DOCTYPE rss [<!ENTITY x "expanded">]><rss><item>&x;</item></rss>',
        "application/rss+xml",
    ))
    packet = web.research_fetch("https://example.test/feed", _ctx(tmp_path))
    assert packet["status"] == "invalid_response"


def test_research_fetch_rejects_utf16_xml_dtd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    xml = (
        '<?xml version="1.0" encoding="utf-16"?>'
        '<!DOCTYPE rss [<!ENTITY x "expanded">]>'
        '<rss><channel><item>&x;</item></channel></rss>'
    ).encode("utf-16")
    _network(monkeypatch, Response(xml, "application/rss+xml"))

    packet = web.research_fetch("https://example.test/feed", _ctx(tmp_path))

    assert packet["status"] == "invalid_response"
    assert "expanded" not in packet["text"]


def test_research_fetch_uses_one_discovered_public_feed_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = Response(
        b'<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head>'
        b"<body>Enable JavaScript</body></html>",
    )
    feed = Response(
        b"<rss><channel><item><title>Public fallback article</title></item></channel></rss>",
        "application/rss+xml",
    )

    class Opener:
        def open(self, request: urllib.request.Request, timeout: int) -> Response:
            return feed if request.full_url.endswith("/feed.xml") else html

    monkeypatch.setattr(web, "pinned_opener", lambda: Opener())
    monkeypatch.setattr(web, "record_tool_receipt", lambda *args, **kwargs: "receipt")
    packet = web.research_fetch("https://example.test/article", _ctx(tmp_path))
    assert packet["status"] == "ok"
    assert packet["requested_url"] == "https://example.test/article"
    assert packet["final_url"] == "https://example.test/final"
    assert len(packet["attempts"]) == 2
    assert "Public fallback article" in packet["text"]


def test_research_fetch_recovers_same_origin_http_hint_as_https(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = []

    class RedirectBody:
        closed = False

        def close(self) -> None:
            self.closed = True

    redirect_body = RedirectBody()

    class CanonicalResponse(Response):
        def geturl(self) -> str:
            return "https://unicode.org/reports/tr15/"

    class Opener:
        def open(self, request: urllib.request.Request, timeout: int):
            opened.append(request.full_url)
            if len(opened) == 1:
                raise urllib.error.HTTPError(
                    request.full_url, 301, "moved",
                    {"Location": "http://unicode.org/reports/tr15/"},
                    redirect_body,
                )
            assert redirect_body.closed
            return CanonicalResponse(b"<article>Canonical document</article>")

    monkeypatch.setattr(web, "pinned_opener", lambda: Opener())
    monkeypatch.setattr(web, "record_tool_receipt", lambda *args, **kwargs: "receipt")

    packet = web.research_fetch("https://unicode.org/reports/tr15", _ctx(tmp_path))

    assert opened == [
        "https://unicode.org/reports/tr15",
        "https://unicode.org/reports/tr15/",
    ]
    assert packet["status"] == "ok"
    assert packet["requested_url"] == "https://unicode.org/reports/tr15"
    assert [attempt["status"] for attempt in packet["attempts"]] == [
        "http_error", "ok",
    ]


@pytest.mark.parametrize("location", [
    "http://example.org/reports/tr15/",
    "http://user:secret@unicode.org/reports/tr15/",
    "http://127.0.0.1/reports/tr15/",
    "http://unicode.org:8080/reports/tr15/",
])
def test_research_fetch_rejects_unsafe_http_canonical_hint(
    location: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = []

    class Opener:
        def open(self, request: urllib.request.Request, timeout: int):
            opened.append(request.full_url)
            raise urllib.error.HTTPError(
                request.full_url, 301, "moved", {"Location": location}, None,
            )

    monkeypatch.setattr(web, "pinned_opener", lambda: Opener())
    monkeypatch.setattr(web, "record_tool_receipt", lambda *args, **kwargs: "receipt")

    packet = web.research_fetch("https://unicode.org/reports/tr15", _ctx(tmp_path))

    assert opened == ["https://unicode.org/reports/tr15"]
    assert packet["status"] == "http_error" and packet["final_url"] is None


def test_research_fetch_canonical_recovery_stops_after_one_redirect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = []

    class Opener:
        def open(self, request: urllib.request.Request, timeout: int):
            opened.append(request.full_url)
            raise urllib.error.HTTPError(
                request.full_url, 301, "moved",
                {"Location": "http://unicode.org/reports/tr15/"}, None,
            )

    monkeypatch.setattr(web, "pinned_opener", lambda: Opener())
    monkeypatch.setattr(web, "record_tool_receipt", lambda *args, **kwargs: "receipt")

    packet = web.research_fetch("https://unicode.org/reports/tr15", _ctx(tmp_path))

    assert opened == [
        "https://unicode.org/reports/tr15",
        "https://unicode.org/reports/tr15/",
    ]
    assert packet["status"] == "http_error"
    assert len(packet["attempts"]) == 2


def test_research_fetch_rejects_cross_origin_final_canonical_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = []

    class CrossOriginResponse(Response):
        def geturl(self) -> str:
            return "https://other.example/reports/tr15/"

    class Opener:
        def open(self, request: urllib.request.Request, timeout: int):
            opened.append(request.full_url)
            if len(opened) == 1:
                raise urllib.error.HTTPError(
                    request.full_url, 301, "moved",
                    {"Location": "http://unicode.org/reports/tr15/"}, None,
                )
            return CrossOriginResponse(b"<article>Other origin</article>")

    monkeypatch.setattr(web, "pinned_opener", lambda: Opener())
    monkeypatch.setattr(web, "record_tool_receipt", lambda *args, **kwargs: "receipt")

    packet = web.research_fetch("https://unicode.org/reports/tr15", _ctx(tmp_path))

    assert packet["status"] == "blocked"
    assert packet["final_url"] is None and packet["text"] == ""


def test_research_fetch_does_not_send_recovery_when_receipt_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = []
    receipts = 0

    class Opener:
        def open(self, request: urllib.request.Request, timeout: int):
            opened.append(request.full_url)
            raise urllib.error.HTTPError(
                request.full_url, 301, "moved",
                {"Location": "http://unicode.org/reports/tr15/"}, None,
            )

    def receipt(*args, **kwargs):
        nonlocal receipts
        receipts += 1
        if receipts == 3:
            raise OSError("receipt unavailable")
        return "receipt"

    monkeypatch.setattr(web, "pinned_opener", lambda: Opener())
    monkeypatch.setattr(web, "record_tool_receipt", receipt)

    packet = web.research_fetch("https://unicode.org/reports/tr15", _ctx(tmp_path))

    assert opened == ["https://unicode.org/reports/tr15"]
    assert packet["status"] == "blocked"
    assert [attempt["status"] for attempt in packet["attempts"]] == [
        "http_error", "blocked",
    ]


def test_research_fetch_does_not_recover_when_failure_receipt_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = []
    receipts = 0

    class RedirectBody:
        closed = False

        def close(self) -> None:
            self.closed = True

    redirect_body = RedirectBody()

    class Opener:
        def open(self, request: urllib.request.Request, timeout: int):
            opened.append(request.full_url)
            raise urllib.error.HTTPError(
                request.full_url, 301, "moved",
                {"Location": "http://unicode.org/reports/tr15/"}, redirect_body,
            )

    def receipt(*args, **kwargs):
        nonlocal receipts
        receipts += 1
        if receipts == 2:
            raise OSError("receipt unavailable")
        return "receipt"

    monkeypatch.setattr(web, "pinned_opener", lambda: Opener())
    monkeypatch.setattr(web, "record_tool_receipt", receipt)

    with pytest.raises(OSError, match="receipt unavailable"):
        web.research_fetch("https://unicode.org/reports/tr15", _ctx(tmp_path))

    assert opened == ["https://unicode.org/reports/tr15"]
    assert redirect_body.closed


def test_research_search_distinguishes_empty_indexes_from_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web, "_search_attempt", lambda cfg, provider, search: [])
    assert web.research_search("query", 5, _ctx(tmp_path))["status"] == "no_results"

    def fail(cfg, provider, search):
        raise OSError("offline")

    monkeypatch.setattr(web, "_search_attempt", fail)
    assert web.research_search("query", 5, _ctx(tmp_path))["status"] == "error"



def test_research_search_enforces_site_scope_for_every_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def results(cfg, provider, search):
        return [{"url": "https://outside.example/result", "title": "outside"}]

    monkeypatch.setattr(web, "_search_attempt", results)
    result = web.research_search(
        "site:unicode.org/reports/tr15 normalization", 5, _ctx(tmp_path),
    )

    assert result["status"] == "no_results"
    assert [item["url"] for item in result["results"]] == [
        "https://unicode.org/reports/tr15",
    ]
    assert result["results"][0]["discovery_method"] == "query_url"


def test_research_search_accepts_site_subdomains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web, "_search_attempt", lambda cfg, provider, search: [{
        "url": "https://docs.unicode.org/spec", "title": "Unicode spec",
    }])
    result = web.research_search("site:unicode.org spec", 5, _ctx(tmp_path))
    assert result["status"] == "ok"
    assert result["results"][0]["url"] == "https://docs.unicode.org/spec"


def test_research_search_prioritizes_explicit_url_with_full_backend_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit = "https://www.rfc-editor.org/rfc/rfc4180"
    monkeypatch.setattr(web, "_search_attempt", lambda cfg, provider, search: [
        {"url": "https://example.org/one", "title": "RFC 4180 CSV one"},
        {"url": "https://example.org/two", "title": "RFC 4180 CSV two"},
        {"url": explicit, "title": "duplicate RFC 4180 CSV"},
    ])

    result = web.research_search(f"RFC 4180 CSV {explicit}", 2, _ctx(tmp_path))

    assert result["status"] == "ok"
    assert [item["url"] for item in result["results"]] == [
        explicit, "https://example.org/one",
    ]
    assert result["results"][0]["discovery_method"] == "query_url"


def test_research_search_filters_every_backend_before_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = []

    def results(cfg, provider, search):
        seen.append(provider)
        if provider != "bing-rss":
            return [{
                "url": "https://myaccount.microsoft.com/login",
                "title": "My Account",
                "snippet": (
                    "Sign in to manage your Microsoft account and access "
                    "Excel securely."
                ),
            }]
        return [{
            "url": "https://support.example.org/excel/csv-import",
            "title": "Excel CSV import",
            "snippet": "Preserve leading zeros during text import.",
        }]

    monkeypatch.setattr(web, "_search_attempt", results)
    result = web.research_search(
        "Excel CSV import quoted fields leading zeros", 5, _ctx(tmp_path),
    )

    assert seen == ["marginalia", "mwmbl", "bing-rss"]
    assert [item["url"] for item in result["results"]] == [
        "https://support.example.org/excel/csv-import",
    ]
    assert result["results"][0]["attempt_statuses"] == [
        {"backend": "marginalia", "status": "no_results"},
        {"backend": "mwmbl", "status": "no_results"},
        {"backend": "bing-rss", "status": "ok"},
    ]


def test_search_relevance_excludes_hostname_tokens_but_keeps_empty_reduction() -> None:
    assert not web._search_result_relevant(
        "Microsoft Excel CSV formula quoted fields",
        {
            "url": "https://myaccount.microsoft.com/login",
            "title": "My Account",
            "snippet": "Access Microsoft Excel securely from any device.",
        },
        site_bound=False,
    )
    assert web._search_result_relevant(
        "RFC 4180",
        {
            "url": "https://rfc.example/spec",
            "title": "RFC 4180 format",
            "snippet": "",
        },
        site_bound=False,
    )


@pytest.mark.parametrize("hit", [
    {"url": "https://[bad", "title": "Excel CSV", "snippet": "CSV import"},
    {"url": None, "title": "Excel CSV", "snippet": "CSV import"},
    {"url": "https://example.org/csv", "title": None, "snippet": "CSV import"},
])
def test_search_relevance_rejects_malformed_backend_hits(hit: dict[str, object]) -> None:
    assert not web._search_result_relevant(
        "Excel CSV import", hit, site_bound=False,
    )


def test_search_relevance_validates_metadata_for_site_only_query() -> None:
    assert not web._search_result_relevant(
        "site:docs.example",
        {"url": "https://docs.example/spec", "title": None},
        site_bound=True,
    )


def test_research_search_unsafe_backend_hit_does_not_block_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def results(cfg, provider, search):
        if provider == "marginalia":
            return [{
                "url": "https://127.0.0.1/csv-import",
                "title": "Excel CSV import",
            }]
        return [{
            "url": "https://docs.example.org/csv-import",
            "title": "Excel CSV import",
        }]

    monkeypatch.setattr(web, "_search_attempt", results)
    result = web.research_search("Excel CSV import", 5, _ctx(tmp_path))

    assert result["results"][0]["url"] == "https://docs.example.org/csv-import"
    assert result["results"][0]["attempt_statuses"] == [
        {"backend": "marginalia", "status": "no_results"},
        {"backend": "mwmbl", "status": "ok"},
    ]


def test_research_search_does_not_hide_partial_or_receipt_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def partial(cfg, provider, search):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("offline")
        return []

    monkeypatch.setattr(web, "_search_attempt", partial)
    result = web.research_search(
        "query https://example.org/spec", 5, _ctx(tmp_path),
    )
    assert result["status"] == "error"
    assert [item["url"] for item in result["results"]] == [
        "https://example.org/spec",
    ]

    monkeypatch.setattr(
        web, "_search_attempt",
        lambda cfg, provider, search: (_ for _ in ()).throw(web._SearchReceiptError()),
    )
    assert web.research_search(
        "query https://example.org/spec", 5, _ctx(tmp_path),
    ) == {
        "query": "query https://example.org/spec", "results": [], "status": "error",
    }


def test_bing_rss_parser_returns_only_public_https_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rss = (
        b"<rss><channel><item><title>SQLite WAL</title>"
        b"<link>https://sqlite.org/wal.html</link><description>Concurrency</description>"
        b"<pubDate>Sun, 06 Sep 2026 00:00:00 GMT</pubDate></item>"
        b"<item><title>Internal</title><link>http://127.0.0.1/private</link></item>"
        b"</channel></rss>"
    )
    _network(monkeypatch, Response(rss, "application/rss+xml"))
    hits = web._bing_rss("sqlite wal", 5)
    assert hits == [{
        "url": "https://sqlite.org/wal.html", "title": "SQLite WAL",
        "snippet": "Concurrency", "published_at": "Sun, 06 Sep 2026 00:00:00 GMT",
    }]


def test_bing_rss_rejects_unrelated_http_200_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rss = (
        b"<rss><channel><item><title>Google Drive sign-in</title>"
        b"<link>https://drive.google.com/</link>"
        b"<description>Cloud file storage</description></item></channel></rss>"
    )
    _network(monkeypatch, Response(rss, "application/rss+xml"))
    assert web._bing_rss("UTR #15 NFC Hangul Jamo composition", 5) == []


def test_bing_rss_filters_before_result_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    junk = b"".join(
        b"<item><title>Cloud storage</title>"
        b"<link>https://example.com/drive</link></item>"
        for _ in range(5)
    )
    rss = (
        b"<rss><channel>" + junk
        + b"<item><title>Unicode normalization</title>"
        b"<link>https://unicode.org/reports/tr15/</link>"
        b"<description>NFC Hangul composition</description></item>"
        b"</channel></rss>"
    )
    _network(monkeypatch, Response(rss, "application/rss+xml"))
    hits = web._bing_rss("Unicode normalization NFC Hangul", 1)
    assert [item["url"] for item in hits] == [
        "https://unicode.org/reports/tr15/",
    ]


def test_bing_rss_accepts_relevant_unicode_multiterm_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rss = (
        b"<rss><channel><item><title>Unicode normalization forms</title>"
        b"<link>https://unicode.org/reports/tr15/</link>"
        b"<description>NFC composition for Hangul syllables</description>"
        b"</item></channel></rss>"
    )
    _network(monkeypatch, Response(rss, "application/rss+xml"))
    hits = web._bing_rss("Unicode normalization NFC Hangul", 5)
    assert [item["url"] for item in hits] == ["https://unicode.org/reports/tr15/"]


def test_bing_rss_one_term_uses_word_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rss = (
        b"<rss><channel>"
        b"<item><title>Unicode Standard</title><link>https://unicode.org/</link></item>"
        b"<item><title>Canva</title><link>https://canva.com/</link></item>"
        b"</channel></rss>"
    )
    _network(monkeypatch, Response(rss, "application/rss+xml"))
    assert [item["title"] for item in web._bing_rss("Unicode", 5)] == ["Unicode Standard"]
    assert web._bing_rss("can", 5) == []


def test_bing_rss_site_only_relies_on_verified_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rss = (
        b"<rss><channel>"
        b"<item><title>Documentation</title><link>https://docs.unicode.org/</link></item>"
        b"<item><title>Other</title><link>https://example.com/</link></item>"
        b"</channel></rss>"
    )
    _network(monkeypatch, Response(rss, "application/rss+xml"))
    assert [item["url"] for item in web._bing_rss("site:unicode.org", 5)] == [
        "https://docs.unicode.org/",
    ]


def test_research_search_does_not_synthesize_explicit_site_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def empty(cfg, provider, search):
        calls.append(provider)
        return []

    monkeypatch.setattr(web, "_search_attempt", empty)
    result = web.research_search(
        "site:sqlite.org/wal.html WAL concurrency", 5, _ctx(tmp_path),
    )
    assert result["status"] == "no_results"
    assert result["results"][0]["url"] == "https://sqlite.org/wal.html"
    assert result["results"][0]["discovery_method"] == "query_url"
    assert calls == ["marginalia", "mwmbl", "bing-rss"]


@pytest.mark.parametrize(("query", "expected"), [
    ("원문 https://unicode.org/Public/UCD/latest/ucd/SpecialCasing.txt 를 수집",
     "https://unicode.org/Public/UCD/latest/ucd/SpecialCasing.txt"),
    ('"https://example.org/spec."를 확인', "https://example.org/spec."),
    ("https://example.org/a'b 확인", "https://example.org/a'b"),
    ("https://example.org/spec. 확인", "https://example.org/spec."),
    ("(https://example.org/wiki/Foo_(bar)) 참고",
     "https://example.org/wiki/Foo_(bar)"),
    ("https://example.org/a%20b?q=x%2Fy#part 확인",
     "https://example.org/a%20b?q=x%2Fy#part"),
])
def test_research_search_keeps_one_explicit_https_url_as_discovery(
    query: str, expected: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web, "_search_attempt", lambda cfg, provider, search: [])

    result = web.research_search(query, 5, _ctx(tmp_path))

    assert result["status"] == "no_results"
    assert result["results"] == [{
        "title": urlsplit(expected).path.rsplit("/", 1)[-1],
        "url": expected, "snippet": "", "published_at": None,
        "backend": None, "discovery_method": "query_url",
        "attempt_statuses": [
            {"backend": "marginalia", "status": "no_results"},
            {"backend": "mwmbl", "status": "no_results"},
            {"backend": "bing-rss", "status": "no_results"},
        ],
    }]


def test_bing_rss_rejects_utf16_entity_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    xml = (
        '<?xml version="1.0" encoding="utf-16"?>'
        '<!DOCTYPE rss [<!ENTITY x "expanded">]>'
        '<rss><channel><item><title>&x;</title>'
        '<link>https://example.test/result</link></item></channel></rss>'
    ).encode("utf-16")
    _network(monkeypatch, Response(xml, "application/rss+xml"))

    with pytest.raises(ValueError, match="malformed XML"):
        web._bing_rss("expanded", 5)


@pytest.mark.parametrize("url", [
    "https://user:secret@example.org/path",
    "https://127.0.0.1/private",
])
def test_research_search_rejects_unsafe_explicit_https_url(
    url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web, "_search_attempt", lambda cfg, provider, search: [])
    assert web.research_search(f"확인 {url}", 5, _ctx(tmp_path))["results"] == []


def test_research_search_does_not_skip_an_unsafe_first_explicit_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web, "_search_attempt", lambda cfg, provider, search: [])
    result = web.research_search(
        "https://127.0.0.1/private https://example.org/public", 5, _ctx(tmp_path),
    )
    assert result["results"] == []


@pytest.mark.parametrize("query", [
    "https://example.org/한글",
    "https://example.org/path를 확인",
])
def test_research_search_does_not_invent_an_ascii_prefix_for_ambiguous_iri(
    query: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web, "_search_attempt", lambda cfg, provider, search: [])
    assert web.research_search(query, 5, _ctx(tmp_path))["results"] == []


def test_research_search_prefers_site_path_and_returns_at_most_one_query_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web, "_search_attempt", lambda cfg, provider, search: [])
    result = web.research_search(
        "site:unicode.org/reports/tr39 https://example.org/one https://example.org/two",
        5, _ctx(tmp_path),
    )
    assert [item["url"] for item in result["results"]] == [
        "https://unicode.org/reports/tr39",
    ]


def test_bing_rss_malformed_xml_is_typed_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _network(monkeypatch, Response(b"<rss><broken>", "application/rss+xml"))
    calls = 0

    def attempt(cfg, provider, search):
        nonlocal calls
        calls += 1
        return search() if provider == "bing-rss" else []

    monkeypatch.setattr(web, "_search_attempt", attempt)
    result = web.research_search("query", 5, _ctx(tmp_path))
    assert calls == 3
    assert result["status"] == "error"


@pytest.mark.parametrize(
    ("code", "status"),
    [(429, "rate_limited"), (503, "service_unavailable")],
)
def test_research_search_preserves_http_failure_class(
    code: int, status: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(cfg, provider, search):
        if provider == "marginalia":
            raise urllib.error.HTTPError("https://search", code, "failed", {}, None)
        return []

    monkeypatch.setattr(web, "_search_attempt", fail)
    assert web.research_search("query", 5, _ctx(tmp_path))["status"] == status
