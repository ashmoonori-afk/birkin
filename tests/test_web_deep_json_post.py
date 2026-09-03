"""Deeply nested JSON on the POST routes that parse it themselves.

json.loads raises RecursionError -- a RuntimeError, not a ValueError -- on
JSON nested past CPython's scanner limit, and _read_body admits 64 KB, i.e.
far more nesting levels than the scanner can survive. The routes that do not
go through parse_object caught only ValueError, so the escaping RecursionError
killed the connection: the peer got a FIN with no HTTP response at all and
could not tell a parse failure from a dead server.

Where that limit sits is itself per-platform -- 5000 nested arrays raise on
Windows and parse fine on Linux and macOS -- so catching RecursionError is
only half the fix: the answer must not depend on whether the interpreter
happened to reach the end of the body. Both routes therefore parse under the
same MAX_NESTING_DEPTH bound and answer 400 with one stable message.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from birkin.web import server as web
from birkin.web.request_payload import MAX_NESTING_DEPTH

def _nested_arrays(depth: int) -> bytes:
    return b"[" * depth + b"]" * depth


# Past what json.loads survives on some platforms but not others (it raises on
# Windows and parses on Linux and macOS)...
_DEEP = _nested_arrays(5000)
# ...and past the bound but well within every platform's scanner, so the walk
# -- not the interpreter -- is what refuses it, everywhere.
_OVER_BOUND = _nested_arrays(MAX_NESTING_DEPTH + 8)
_MALFORMED = b'{"unterminated": '


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


def test_the_shallower_deep_body_is_one_every_scanner_accepts() -> None:
    # Given: the premise of the _OVER_BOUND cases -- what refuses this body is
    # the bound the routes enforce, not the interpreter the test happens to run.
    assert isinstance(json.loads(_OVER_BOUND), list)


@pytest.mark.parametrize("body", [_DEEP, _OVER_BOUND, _MALFORMED])
def test_a2a_answers_a_parse_error_instead_of_dropping_the_connection(
    live, body: bytes
) -> None:
    base = live({"a2a_enabled": True})
    code, payload = _post_raw(f"{base}/a2a", body)
    assert code == 400
    assert json.loads(payload)["error"]["code"] == -32700


@pytest.mark.parametrize("body", [_DEEP, _OVER_BOUND])
def test_workspace_answers_too_deep_instead_of_dropping_the_connection(
    live, body: bytes
) -> None:
    base = live({})
    code, payload = _post_raw(f"{base}/api/workspace/sessions", body)
    assert code == 400
    assert json.loads(payload)["error"] == "JSON nesting too deep"


def test_workspace_answers_bad_json_for_a_malformed_body(live) -> None:
    base = live({})
    code, payload = _post_raw(f"{base}/api/workspace/sessions", _MALFORMED)
    assert code == 400
    assert json.loads(payload)["error"] == "bad json"
