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
