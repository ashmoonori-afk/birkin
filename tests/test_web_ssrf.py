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
