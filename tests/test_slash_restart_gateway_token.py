"""Regression: the REPL /restart must authenticate against the gateway.

The local HTTP channel checks ``X-Birkin-Token`` before it reads the request
body (birkin/gateway/channels/local_http.py), and a token is required in every
configuration except ``gateway.http.insecure_no_token``. A ``/restart`` that
sends no capability header is therefore answered 401 -- which, because
``HTTPError`` subclasses ``URLError``, used to be reported as "Gateway not
reachable" and pointed the user at the wrong cause.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

from birkin import slashcommands as sc
from birkin.gateway.channels import capability_file


class _Response:
    """Minimal stand-in for the object ``urlopen`` yields."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


def test_gateway_post_sends_the_capability_token(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("BIRKIN_HTTP_TOKEN", raising=False)
    monkeypatch.setattr(
        capability_file, "load_or_create_token",
        lambda: ("capability-token", tmp_path / "gateway_http_token"))
    seen: list[urllib.request.Request] = []

    def _urlopen(req: urllib.request.Request, timeout: float | None = None):
        seen.append(req)
        return _Response(b'{"reply": "restarting"}')

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    reply = sc._gateway_post({"gateway_port": 8788}, "/restart-gateway")
    assert reply == "restarting"
    assert seen[0].get_header("X-birkin-token") == "capability-token"


def test_gateway_post_prefers_the_environment_token(monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HTTP_TOKEN", "env-token")
    seen: list[urllib.request.Request] = []

    def _urlopen(req: urllib.request.Request, timeout: float | None = None):
        seen.append(req)
        return _Response(b'{"reply": "ok"}')

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    _ = sc._gateway_post({"gateway_port": 8788}, "/hard-restart")
    assert seen[0].get_header("X-birkin-token") == "env-token"


def test_gateway_post_reports_a_rejected_token_not_a_dead_gateway(
    monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HTTP_TOKEN", "stale-token")

    def _urlopen(req: urllib.request.Request, timeout: float | None = None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    out = sc._gateway_post({"gateway_port": 8788}, "/restart-gateway")
    assert "401" in out
    assert "BIRKIN_HTTP_TOKEN" in out
    assert "not reachable" not in out
