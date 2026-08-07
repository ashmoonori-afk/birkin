"""Local HTTP channel: a tiny REST endpoint to talk to the agent.

    POST /message   {"session": "<id>", "text": "..."}  -> {"reply": "..."}
    GET  /health                                          -> {"ok": true}

Bound to 127.0.0.1 with a Host-header check so only local clients reach it.
Lets scripts, editors, or other tools drive birkin programmatically.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

from .base import Channel

if TYPE_CHECKING:
    from ..core import Gateway

_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
_MAX_BODY = 1_000_000  # 1 MB cap on a request body — this endpoint takes a chat line
# Optional shared secret. When BIRKIN_HTTP_TOKEN is set, /message requires a
# matching X-Birkin-Token header (defense-in-depth lockdown; off by default so
# existing local clients keep working).
_HTTP_TOKEN = (os.environ.get("BIRKIN_HTTP_TOKEN") or "").strip()


class LocalHTTPChannel(Channel):
    name = "http"

    def __init__(self, port: int):
        self.port = port
        self._ready = threading.Event()
        self._stop_requested = threading.Event()
        self._httpd: ThreadingHTTPServer | None = None
        self._lifecycle_lock = threading.Lock()

    def wait_until_ready(self, timeout: float | None = None) -> bool:
        """Wait until the listener is bound and its actual port is published."""
        return self._ready.wait(timeout)

    def stop(self) -> None:
        """Stop a running listener from its owning thread."""
        self._stop_requested.set()
        with self._lifecycle_lock:
            httpd = self._httpd
        if httpd is not None:
            try:
                with socket.create_connection(
                        httpd.server_address, timeout=1.0):
                    pass
            except OSError:
                pass

    def start(self, gateway: "Gateway") -> None:
        self._stop_requested.clear()
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
                # CSRF defense: require Content-Type application/json. A browser
                # on a malicious page can only send a "simple" request
                # (text/plain, form, multipart) without a CORS preflight; an
                # application/json POST forces a preflight, which we never answer.
                # This blocks a visited website from driving the agent. Legit
                # local clients already send JSON.
                ctype = (self.headers.get("Content-Type", "") or "").split(";", 1)[0].strip().lower()
                if ctype != "application/json":
                    self._json({"error": "Content-Type must be application/json"}, 415); return
                # Optional shared-secret lockdown (off unless BIRKIN_HTTP_TOKEN set).
                if _HTTP_TOKEN and self.headers.get("X-Birkin-Token", "") != _HTTP_TOKEN:
                    self._json({"error": "unauthorized"}, 401); return
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
                channel = payload.get("channel", "http")
                if channel not in {"http", "voice"}:
                    self._json({"error": "invalid channel"}, 400); return
                if not text:
                    self._json({"error": "empty text"}, 400); return
                reply = gw.handle(channel, session_id, text)
                self._json({"reply": reply})
                if gw.pending_hard_restart:
                    try:
                        self.wfile.flush()
                    except OSError:
                        pass
                    gw.do_hard_restart()  # replaces the process; never returns

        httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        with self._lifecycle_lock:
            if self._httpd is not None:
                httpd.server_close()
                raise RuntimeError("HTTP channel is already running")
            self._httpd = httpd
            self.port = int(httpd.server_address[1])
            self._ready.set()
        print(f"  · http channel on http://127.0.0.1:{self.port} "
              f"(POST /message, GET /health)")
        try:
            while not self._stop_requested.is_set():
                httpd.handle_request()
        finally:
            httpd.server_close()
            with self._lifecycle_lock:
                if self._httpd is httpd:
                    self._httpd = None
                    self._ready.clear()
