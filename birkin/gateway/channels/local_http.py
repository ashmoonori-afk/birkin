"""Local HTTP channel: a tiny REST endpoint to talk to the agent.

    POST /message   {"session": "<id>", "text": "..."}  -> {"reply": "..."}
    GET  /health                                          -> {"ok": true}

Bound to 127.0.0.1 with a Host-header check so only local clients reach it.
Lets scripts, editors, or other tools drive birkin programmatically.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any

from .base import Channel

if TYPE_CHECKING:
    from ..core import Gateway

_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


class LocalHTTPChannel(Channel):
    name = "http"

    def __init__(self, port: int):
        self.port = port

    def start(self, gateway: "Gateway") -> None:
        gw = gateway

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _host_ok(self) -> bool:
                host = (self.headers.get("Host", "") or "").rsplit(":", 1)[0]
                return host in _ALLOWED_HOSTS or host == ""

            def _json(self, obj: Any, code: int = 200) -> None:
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if not self._host_ok():
                    self._json({"error": "forbidden host"}, 403); return
                if self.path == "/health":
                    self._json({"ok": True, "channel": "http"})
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self) -> None:
                if not self._host_ok():
                    self._json({"error": "forbidden host"}, 403); return
                if self.path != "/message":
                    self._json({"error": "not found"}, 404); return
                # Tolerate junk: bad Content-Length, non-UTF-8 bytes (port
                # scanners / wrong-encoding clients), or non-object JSON must
                # return 400 — never crash the request handler.
                try:
                    length = int(self.headers.get("Content-Length", 0) or 0)
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except (ValueError, UnicodeDecodeError):
                    self._json({"error": "bad request"}, 400); return
                if not isinstance(payload, dict):
                    self._json({"error": "expected a JSON object"}, 400); return
                text = (payload.get("text") or "").strip()
                session_id = str(payload.get("session", "default"))
                if not text:
                    self._json({"error": "empty text"}, 400); return
                reply = gw.handle("http", session_id, text)
                self._json({"reply": reply})

        httpd = HTTPServer(("127.0.0.1", self.port), Handler)
        print(f"  · http channel on http://127.0.0.1:{self.port} "
              f"(POST /message, GET /health)")
        try:
            httpd.serve_forever()
        finally:
            httpd.server_close()
