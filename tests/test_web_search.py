"""web_search: Marginalia first, Mwmbl when it can't answer, honest error.

No network. A fake opener stands in for the real one so the response *shapes*
of both services are exercised — the shapes are the whole reason two backends
need separate parsers.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from birkin.tools import web


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


class _Opener:
    """Answers by host. A host with no entry raises, like a dead service."""

    def __init__(self, by_host):
        self.by_host = by_host
        self.calls = []

    def open(self, req, timeout=None):
        host = req.host if hasattr(req, "host") else ""
        self.calls.append((host, req.full_url, dict(req.headers)))
        answer = self.by_host.get(host)
        if answer is None:
            raise urllib.error.HTTPError(req.full_url, 503, "Service "
                                         "Unavailable", {}, None)
        if isinstance(answer, Exception):
            raise answer
        return _Resp(json.dumps(answer).encode("utf-8"))


MARGINALIA_OK = {
    "license": "CC-BY-NC-SA 4.0",
    "results": [
        {"url": "https://example.org/a", "title": "Async in Python",
         "description": "A note on event loops."},
        {"url": "https://example.org/b", "title": "More", "description": ""},
    ],
}

# Mwmbl returns a bare array, and title/extract are *segment lists* used for
# bolding query terms — not strings.
MWMBL_OK = [
    {"url": "https://mwmbl.example/x",
     "title": [{"value": "Event ", "is_bold": False},
               {"value": "loops", "is_bold": True}],
     "extract": [{"value": "How they schedule.", "is_bold": False}]},
]


def _install(monkeypatch, by_host):
    opener = _Opener(by_host)
    monkeypatch.setattr(web.urllib.request, "build_opener",
                        lambda *a, **k: opener)
    return opener


def test_marginalia_answers(monkeypatch):
    opener = _install(monkeypatch, {"api2.marginalia-search.com":
                                    MARGINALIA_OK})
    res = web._web_search({"query": "event loops"}, None)
    assert not res.is_error
    assert "https://example.org/a" in res.content
    assert "Async in Python" in res.content
    assert "CC-BY-NC-SA 4.0" in res.content     # attribution rides along
    assert len(opener.calls) == 1               # no fallback needed
    assert opener.calls[0][2].get("Api-key") == "public"


def test_falls_back_to_mwmbl_on_rate_limit(monkeypatch):
    opener = _install(monkeypatch, {"api.mwmbl.org": MWMBL_OK})
    res = web._web_search({"query": "event loops"}, None)
    assert not res.is_error
    assert "https://mwmbl.example/x" in res.content
    assert "Event loops" in res.content         # segments joined, not repr'd
    assert "How they schedule." in res.content
    assert "CC-BY-NC-SA" not in res.content     # not Marginalia's results
    assert len(opener.calls) == 2               # tried Marginalia first


def test_empty_marginalia_also_falls_back(monkeypatch):
    """Zero results is a miss, not an answer — the fallback exists for it."""
    opener = _install(monkeypatch, {"api2.marginalia-search.com":
                                    {"results": []},
                                    "api.mwmbl.org": MWMBL_OK})
    res = web._web_search({"query": "event loops"}, None)
    assert not res.is_error
    assert "mwmbl.example" in res.content
    assert len(opener.calls) == 2


def test_both_down_reports_both(monkeypatch):
    _install(monkeypatch, {})
    res = web._web_search({"query": "event loops"}, None)
    assert res.is_error
    assert "Marginalia" in res.content and "Mwmbl" in res.content


def test_no_retry_on_failure(monkeypatch):
    """The public key's bucket is shared with every other birkin user; a retry
    loop here degrades the service for everyone."""
    opener = _install(monkeypatch, {})
    web._web_search({"query": "x"}, None)
    hosts = [c[0] for c in opener.calls]
    assert hosts == ["api2.marginalia-search.com", "api.mwmbl.org"]


def test_missing_query_is_an_error(monkeypatch):
    opener = _install(monkeypatch, {"api2.marginalia-search.com":
                                    MARGINALIA_OK})
    res = web._web_search({"query": "   "}, None)
    assert res.is_error
    assert not opener.calls          # never went out


def test_count_is_clamped(monkeypatch):
    opener = _install(monkeypatch, {"api2.marginalia-search.com":
                                    MARGINALIA_OK})
    web._web_search({"query": "x", "count": 9999}, None)
    assert f"count={web.MAX_RESULTS}" in opener.calls[0][1]


def test_query_is_escaped(monkeypatch):
    """A query is user/model text; it must not be able to add parameters."""
    opener = _install(monkeypatch, {"api2.marginalia-search.com":
                                    MARGINALIA_OK})
    web._web_search({"query": "a&count=1&b c"}, None)
    url = opener.calls[0][1]
    assert "a%26count%3D1%26b%20c" in url
    assert url.count("count=") == 1


def test_korean_query_survives_the_url(monkeypatch):
    opener = _install(monkeypatch, {"api2.marginalia-search.com":
                                    MARGINALIA_OK})
    web._web_search({"query": "파이썬 비동기"}, None)
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(opener.calls[0][1]).query)["query"][0]
    assert q == "파이썬 비동기"


def test_api_key_override(monkeypatch):
    opener = _install(monkeypatch, {"api2.marginalia-search.com":
                                    MARGINALIA_OK})
    monkeypatch.setenv("MARGINALIA_API_KEY", "mine")
    web._web_search({"query": "x"}, None)
    assert opener.calls[0][2].get("Api-key") == "mine"


def test_registered_and_not_parallel_safe():
    from birkin import parallel
    names = [t.name for t in web.tools()]
    assert "web_search" in names
    # Fanning this out in parallel would burn a rate-limit bucket shared with
    # every other user of the public key.
    assert "web_search" not in parallel.PARALLEL_SAFE_TOOLS


def test_tool_description_states_the_coverage_limit():
    tool = next(t for t in web.tools() if t.name == "web_search")
    assert "not indexed" in tool.description
