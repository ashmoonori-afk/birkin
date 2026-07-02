"""SSRF guard for web_fetch — block loopback / private / link-local / reserved.

Uses literal IPs so no network/DNS is needed (getaddrinfo on a numeric host is
offline).
"""

from __future__ import annotations

from birkin.tools import web


def test_blocks_loopback_and_localhost():
    assert web._is_blocked_url("http://127.0.0.1/x") is True
    assert web._is_blocked_url("http://localhost:8788/message") is True
    assert web._is_blocked_url("http://[::1]/x") is True


def test_blocks_link_local_metadata_and_private():
    assert web._is_blocked_url("http://169.254.169.254/latest/meta-data/") is True
    assert web._is_blocked_url("http://10.0.0.5/admin") is True
    assert web._is_blocked_url("http://192.168.1.1/") is True


def test_allows_public_literal_ip():
    # 93.184.216.34 (example.com) — public, numeric so no DNS lookup needed.
    assert web._is_blocked_url("https://93.184.216.34/") is False


def test_web_fetch_refuses_blocked(monkeypatch):
    called = {"n": 0}

    def boom(*a, **k):  # must NOT be reached for a blocked URL
        called["n"] += 1
        raise AssertionError("urlopen should not run for a blocked URL")
    monkeypatch.setattr(web.urllib.request, "urlopen", boom)
    res = web._web_fetch({"url": "http://127.0.0.1:8787/api/approvals"}, None)
    assert res.is_error and "SSRF" in res.content
    assert called["n"] == 0


def test_redirect_to_blocked_address_is_refused():
    # The guard must re-run on each redirect hop: a public URL that 302s to the
    # cloud-metadata IP would otherwise bypass the up-front check.
    import urllib.error

    handler = web._GuardedRedirectHandler()
    try:
        handler.redirect_request(
            req=None, fp=None, code=302, msg="Found", headers={},
            newurl="http://169.254.169.254/latest/meta-data/")
        raise AssertionError("expected an HTTPError for a blocked redirect target")
    except urllib.error.HTTPError as exc:
        assert "SSRF" in str(exc.reason)


def test_redirect_to_public_address_is_allowed():
    handler = web._GuardedRedirectHandler()
    # A public redirect target should not be blocked by our guard (it returns a
    # Request from the parent handler, not an HTTPError).
    out = handler.redirect_request(
        req=_DummyReq(), fp=None, code=302, msg="Found", headers={},
        newurl="https://93.184.216.34/next")
    assert out is not None


class _DummyReq:
    """Minimal stand-in for urllib's Request, enough for redirect_request()."""
    def get_full_url(self):
        return "https://93.184.216.34/start"

    def get_method(self):
        return "GET"

    headers: dict = {}
    unredirected_hdrs: dict = {}
    def has_header(self, _name):
        return False

    @property
    def origin_req_host(self):
        return "93.184.216.34"

    @property
    def unverifiable(self):
        return True

    timeout = None
