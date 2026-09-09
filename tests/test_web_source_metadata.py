"""Web tools expose enough source metadata to assess recency."""

from __future__ import annotations

from datetime import datetime, timezone
import gzip
import io
import socket
from types import TracebackType
import urllib.request

import pytest

from birkin.tools import web
from birkin.tools.web_document import extract_document


class _Response(io.BytesIO):
    def __init__(self, body: bytes) -> None:
        super().__init__(body)
        self.headers = {
            "Content-Type": "text/html; charset=utf-8",
            "Content-Encoding": "gzip",
            "Last-Modified": "Wed, 29 Jul 2026 10:00:00 GMT",
        }

    def __enter__(self) -> "_Response":
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()

    def geturl(self) -> str:
        return "https://example.com/final-report"


class _Opener:
    def open(
        self,
        _request: urllib.request.Request,
        timeout: float = 30,
    ) -> _Response:
        del timeout
        return _Response(gzip.compress(
            b"<html><head>"
            b'<meta property="article:published_time" '
            b'content="2026-07-28T09:00:00+00:00">'
            b'<meta property="article:modified_time" '
            b'content="2026-07-29T10:00:00+00:00">'
            b"</head><body><h1>Verified report</h1></body></html>"
        ))


class _BrokenGzipOpener:
    def open(
        self,
        _request: urllib.request.Request,
        timeout: float = 30,
    ) -> _Response:
        del timeout
        return _Response(b"not a gzip stream")


def test_web_fetch_returns_exact_source_dates_and_retrieval_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *_handlers: _Opener(),
    )
    monkeypatch.setattr(
        web,
        "_utc_now",
        lambda: datetime(2026, 7, 30, 4, 0, tzinfo=timezone.utc),
        raising=False,
    )

    result = web._web_fetch({"url": "https://example.com/report"}, None)

    assert result.is_error is False
    assert "URL: https://example.com/final-report" in result.content
    assert "Retrieved-At: 2026-07-30T04:00:00+00:00" in result.content
    assert "Published-At: 2026-07-28T09:00:00+00:00" in result.content
    assert "Modified-At: 2026-07-29T10:00:00+00:00" in result.content
    assert (
        "HTTP-Last-Modified: Wed, 29 Jul 2026 10:00:00 GMT"
        in result.content
    )
    assert "# Content\n\nVerified report" in result.content


def test_web_fetch_rejects_malformed_compressed_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *_handlers: _BrokenGzipOpener(),
    )

    result = web._web_fetch({"url": "https://example.com/report"}, None)

    assert result.is_error is True
    assert "invalid compressed response" in result.content


def test_web_search_marks_snippets_as_discovery_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web,
        "_utc_now",
        lambda: datetime(2026, 7, 30, 4, 0, tzinfo=timezone.utc),
        raising=False,
    )

    rendered = web._render(
        [{
            "url": "https://example.com/report",
            "title": "Report",
            "snippet": "A search excerpt.",
        }],
        "Example",
    )

    assert "Retrieved-At: 2026-07-30T04:00:00+00:00" in rendered
    assert "discovery only" in rendered
    assert "publication/update date unavailable" in rendered


def test_web_tool_descriptions_require_opening_exact_sources() -> None:
    tools = {tool.name: tool for tool in web.tools()}

    assert "source metadata" in tools["web_fetch"].description
    assert "discovery only" in tools["web_search"].description
    assert "publication/update date" in tools["web_search"].description


def test_html_extraction_preserves_inline_quote_and_punctuation() -> None:
    document = extract_document(
        "<main><p>In <a href='/wal'>WAL mode</a>, SQLite exhibits "
        '"snapshot <em>isolation</em>".</p></main>'
    )
    assert document.text == (
        'In WAL mode, SQLite exhibits "snapshot isolation".'
    )


def test_html_extraction_separates_blocks_and_keeps_meaningful_spaces() -> None:
    document = extract_document(
        "<article><p>First <strong>important</strong> sentence.</p>"
        "<p>Second\n sentence.</p><div>Third block.</div></article>"
    )
    assert document.text.splitlines() == [
        "First important sentence.",
        "Second sentence.",
        "Third block.",
    ]


def test_html_extraction_ignores_non_content_tags() -> None:
    document = extract_document(
        "<head><meta property='article:published_time' content='2026-09-06'>"
        "<title>Hidden title</title></head><nav>Menu links</nav>"
        "<main>Useful <span>content</span>.</main>"
        "<script>secret()</script><style>.hidden{}</style><noscript>fallback</noscript>"
    )
    assert document.text == "Useful content."
    assert document.published_at == "2026-09-06"


def test_html_extraction_preserves_preformatted_code_across_inline_tags() -> None:
    document = extract_document(
        "<pre>if ready:\n    <code>return</code>  value\nnext()</pre>"
        "<p>After code.</p>"
    )
    assert document.text == (
        "if ready:\n    return  value\nnext()\n"
        "After code."
    )


def test_html_extraction_preserves_table_rows_and_cell_order() -> None:
    document = extract_document(
        "<table><thead><tr><th>Form</th><th>Relation</th><th>Base</th></tr></thead>"
        "<tbody><tr><td><strong>Circled</strong> variants</td><td>① →</td><td>1</td></tr>"
        "<tr><td>Hangul <div>&amp; conjoining jamo</div></td>"
        "<td><a href='/jamo'>가 ↔</a></td><td><pre>ᄀ +ᅡ</pre>"
        "<script>discarded()</script></td></tr>"
        "<tr><td></td><td>Empty left</td><td>Z</td></tr></tbody></table>"
    )

    assert document.text.splitlines() == [
        "Form | Relation | Base",
        "Circled variants | ① → | 1",
        "Hangul & conjoining jamo | 가 ↔ | ᄀ +ᅡ",
        "| Empty left | Z",
    ]
    assert document.links == (("/jamo", "가 ↔"),)


def test_html_extraction_preserves_implicit_and_nested_table_row_boundaries() -> None:
    implicit = extract_document(
        "<table><tr><td>A<td>B<tr><td>C<td>D</table>"
    )
    nested = extract_document(
        "<table><tr><td>Outer<table><tr><td>N1<td>N2"
        "<tr><td>N3<td>N4</table><td>Tail</tr></table>"
    )

    assert implicit.text.splitlines() == ["A | B", "C | D"]
    assert nested.text.splitlines() == ["Outer", "N1 | N2", "N3 | N4", "Tail"]


def test_hidden_navigation_keeps_visible_word_boundary() -> None:
    document = extract_document(
        "<p>before</p><nav>hidden menu</nav><p>after</p>"
    )
    assert document.text == "before\nafter"


def test_html_extraction_collects_actual_anchor_metadata() -> None:
    document = extract_document(
        '<p>See <a href="../reports/tr15/#forms">Unicode '
        '<strong>normalization</strong></a>.</p>'
        '<nav><a href="/menu">Hidden menu</a></nav>'
    )

    assert document.links == ((
        "../reports/tr15/#forms", "Unicode normalization",
    ),)


def test_html_extraction_preserves_links_for_post_resolution_filtering() -> None:
    document = extract_document("".join(
        f'<a href="/{index}">{"x" * 300}</a>' for index in range(600)
    ))

    assert len(document.links) == 600
    assert document.links[-1][0] == "/599"
    assert len(document.links[-1][1]) == 256
