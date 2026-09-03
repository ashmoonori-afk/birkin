"""Deeply nested JSON on the POST routes that parse it themselves.

json.loads raises RecursionError -- a RuntimeError, not a ValueError -- on
JSON nested past CPython's scanner limit, and _read_body admits 64 KB, i.e.
far more nesting levels than the scanner can survive. The routes that do not
go through parse_object caught only ValueError, so the escaping RecursionError
killed the connection: the peer got a FIN with no HTTP response at all and
could not tell a parse failure from a dead server.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from birkin.web import server as web

_DEEP = b"[" * 5000 + b"]" * 5000


@pytest.fixture()
def live(monkeypatch, tmp_path):
    """A real dashboard server on an ephemeral port."""
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    started: list = []

    def _start(cfg):
        monkeypatch.setattr(web.config, "load_config", lambda: cfg)
        httpd = HTTPServer(("127.0.0.1", 0), web.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        started.append((httpd, thread))
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield _start
    for httpd, thread in started:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _post_raw(url: str, body: bytes) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json",
                 "X-Birkin-Token": web._TOKEN})
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_a2a_answers_a_parse_error_instead_of_dropping_the_connection(live) -> None:
    base = live({"a2a_enabled": True})
    code, body = _post_raw(f"{base}/a2a", _DEEP)
    assert code == 400
    assert json.loads(body)["error"]["code"] == -32700


def test_workspace_answers_bad_json_instead_of_dropping_the_connection(live) -> None:
    base = live({})
    code, body = _post_raw(f"{base}/api/workspace/sessions", _DEEP)
    assert code == 400
    assert json.loads(body)["error"] == "bad json"
