"""An early 403 must not leave the request body unread on the socket.

do_POST refuses a bad host or a missing token before reading the body. On
Windows, closing a connection while unread request bytes sit in the socket
buffer sends RST, so the client gets WinError 10053 instead of the 403 it was
owed -- which is exactly how test_post_approvals_token_and_host_gates failed
intermittently (4/5 pass in isolation).

Timing races cannot be pinned by timing, so this pins the invariant instead:
after any early refusal, the body the client declared has been consumed.
"""

from __future__ import annotations

import email.message
import io

from birkin.web import server as web


def _handler(body: bytes, headers: dict[str, str], path: str = "/api/approvals"):
    h = web.Handler.__new__(web.Handler)
    h.rfile = io.BytesIO(body)
    h.wfile = io.BytesIO()
    h.command = "POST"
    h.path = path
    h.request_version = "HTTP/1.1"
    h.requestline = f"POST {path} HTTP/1.1"
    h.client_address = ("127.0.0.1", 0)
    h.close_connection = True
    msg = email.message.Message()
    for key, value in headers.items():
        msg[key] = value
    h.headers = msg
    return h

BODY = b'{"id": "abc123", "action": "approve"}'


class TestEarlyRefusalsDrainTheBody:
    def test_missing_token_403_consumes_the_body(self) -> None:
        h = _handler(BODY, {"Host": "127.0.0.1",
                            "Content-Length": str(len(BODY))})
        h.do_POST()
        assert b"403" in h.wfile.getvalue().splitlines()[0]
        assert h.rfile.read() == b"", "body left unread -> Windows RSTs the 403"

    def test_forbidden_host_403_consumes_the_body(self) -> None:
        h = _handler(BODY, {"Host": "evil.example",
                            "Content-Length": str(len(BODY))})
        h.do_POST()
        assert b"403" in h.wfile.getvalue().splitlines()[0]
        assert h.rfile.read() == b""

    def test_unknown_path_404_consumes_the_body(self) -> None:
        h = _handler(BODY, {"Host": "127.0.0.1",
                            "X-Birkin-Token": web._TOKEN,
                            "Content-Length": str(len(BODY))},
                     path="/nope")
        h.do_POST()
        assert b"404" in h.wfile.getvalue().splitlines()[0]
        assert h.rfile.read() == b""

    def test_a2a_disabled_404_consumes_the_body(self, monkeypatch) -> None:
        monkeypatch.setattr(web.config, "load_config",
                            lambda: {"a2a_enabled": False})
        h = _handler(BODY, {"Host": "127.0.0.1",
                            "X-Birkin-Token": web._TOKEN,
                            "Content-Length": str(len(BODY))},
                     path="/a2a")
        h.do_POST()
        assert b"404" in h.wfile.getvalue().splitlines()[0]
        assert h.rfile.read() == b""


class TestTheDrainIsBounded:
    def test_an_oversized_body_is_abandoned_not_read(self) -> None:
        """Draining is a courtesy to the client, not an obligation to an
        attacker: a body over the POST cap is left where it is."""
        h = _handler(BODY, {"Host": "127.0.0.1",
                            "Content-Length": str(web.MAX_POST_BODY_BYTES + 1)})
        h.do_POST()
        assert h.rfile.read() == BODY          # untouched

    def test_a_garbage_content_length_does_not_crash_the_refusal(self) -> None:
        h = _handler(BODY, {"Host": "127.0.0.1",
                            "Content-Length": "not-a-number"})
        h.do_POST()
        assert b"403" in h.wfile.getvalue().splitlines()[0]
