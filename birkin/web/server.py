"""birkin monitoring dashboard — standard-library HTTP server.

The WebUI is a **dashboard**, not a chat client (chat lives in `birkin chat`).
It is read-mostly and reflects state written by the daemon / Morpheus routine,
plus an approve/reject action for pending proposals.

Endpoints:
- ``GET  /``              -> dashboard SPA
- ``GET  /api/status``    -> model, vault, skills, daemon, next Morpheus, counts
- ``GET  /api/jobs``      -> scheduled cron jobs + daemon heartbeat
- ``GET  /api/runs``      -> recent Morpheus / cron run summaries
- ``GET  /api/approvals`` -> pending proposed actions
- ``POST /api/approvals`` -> {id, action: "approve"|"reject"}
- ``GET  /api/skills``    -> skill catalog

No API key is required to view the dashboard (it does not call the LLM).
"""

from __future__ import annotations

import json
import re
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Optional

from .. import __version__, approvals, config, cron, store
from ..skills import build_manager

_STATIC = Path(__file__).resolve().parent / "static"
MAX_POST_BODY_BYTES = 65_536
POST_BODY_TIMEOUT_SECONDS = 2.0
_APPROVAL_ID_RE = re.compile(r"[0-9a-f]{12}")

# A per-process token embedded in the page and required on mutating POSTs.
# Combined with a Host-header check this blocks DNS-rebinding and other local
# processes from approving queued actions.
_TOKEN = secrets.token_urlsafe(18)
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


def _status_payload() -> dict[str, Any]:
    cfg = config.load_config()
    skills_error = None
    try:
        skills_count = len(build_manager(cfg).skills)
    except Exception:
        skills_count = None
        skills_error = "unavailable"
    from .. import budget as budget_mod
    st = store.read_status()
    stale = store.is_status_stale(st)
    payload = {
        "version": __version__,
        "model": cfg.get("model"),
        "provider": cfg.get("provider"),
        "vault": str(config.vault_dir(cfg)),
        "skills_count": skills_count,
        "auto_approve": cfg.get("auto_approve", []),
        # A stale heartbeat means the daemon died — never claim it's running.
        "daemon": bool(st.get("daemon")) and not stale,
        "stale": stale,
        # Canonical (Morpheus) keys plus legacy aliases so existing dashboard
        # JS / external scripts that still read the old names keep working.
        "next_morpheus": st.get("next_morpheus") or st.get("next_nightly"),
        "next_nightly": st.get("next_nightly") or st.get("next_morpheus"),
        "morpheus_hour": cfg.get("morpheus_hour", cfg.get("nightly_hour", 4)),
        "nightly_hour": cfg.get("morpheus_hour", cfg.get("nightly_hour", 4)),
        "pending_count": len(approvals.reviewable_pending()),
        "heartbeat": st.get("heartbeat"),
        "budget": budget_mod.status(cfg),
    }
    if skills_error:
        payload["skills_error"] = skills_error
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = f"birkin-dashboard/{__version__}"

    def log_message(self, *args: Any) -> None:
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host", "") or "").rsplit(":", 1)[0]
        return host in _ALLOWED_HOSTS or host == ""

    def _read_body(self) -> tuple[bytes | None, int]:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else -1
        except ValueError:
            length = -1
        if length < 0:
            self.close_connection = True
            return None, 400
        if length > MAX_POST_BODY_BYTES:
            self.close_connection = True
            return None, 413
        previous_timeout = self.connection.gettimeout()
        try:
            self.connection.settimeout(POST_BODY_TIMEOUT_SECONDS)
            body = self.rfile.read(length)
        except TimeoutError:
            self.close_connection = True
            return None, 408
        finally:
            self.connection.settimeout(previous_timeout)
        if len(body) != length:
            self.close_connection = True
            return None, 400
        return body, 200

    def do_GET(self) -> None:
        if not self._host_ok():
            self._send(403, b"forbidden host", "text/plain")
            return
        if self.path in ("/", "/index.html"):
            html = (_STATIC / "index.html").read_text(encoding="utf-8")
            html = html.replace("__BIRKIN_TOKEN__", _TOKEN)
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._json(_status_payload())
        elif self.path == "/api/jobs":
            self._json({"status": store.read_status(), "jobs": cron.load_jobs()})
        elif self.path == "/api/runs":
            self._json(store.list_runs(limit=20))
        elif self.path == "/api/approvals":
            from .. import risk as risk_mod
            items = risk_mod.sort_by_risk(approvals.reviewable_pending())
            for it in items:
                it["risk"] = risk_mod.risk_for(it.get("category", ""))
            self._json(items)
        elif self.path == "/api/skills":
            cfg = config.load_config()
            try:
                mgr = build_manager(cfg)
                self._json([{"name": s.name, "description": s.description,
                             "source": s.source}
                            for s in sorted(mgr.skills.values(), key=lambda x: x.name)])
            except Exception as exc:
                self._json({"error": str(exc)}, code=500)
        elif self.path == "/.well-known/agent-card.json":
            # Discovery only: the card names what birkin can do and where
            # to ask. It needs no token -- a peer must be able to read it
            # before it has been given one -- and it carries no secrets.
            from .. import a2a
            cfg = config.load_config()
            if not a2a.enabled(cfg):
                self._send(404, b"not found", "text/plain")
                return
            host = self.headers.get("Host") or "127.0.0.1"
            self._json(a2a.agent_card(f"http://{host}", cfg))
        else:
            self._send(404, b"not found", "text/plain")

    def _handle_a2a(self) -> None:
        """One A2A JSON-RPC call.

        Reached only after do_POST has checked the dashboard token: this
        endpoint submits work, which is at least as consequential as
        approving it. While the feature is off it is a plain 404, so a
        scan cannot tell birkin from a birkin without A2A.
        """
        from .. import a2a
        cfg = config.load_config()
        if not a2a.enabled(cfg):
            self._drain_body()
            self._send(404, b"not found", "text/plain")
            return
        body, body_status = self._read_body()
        if body_status != 200:
            self._json({"error": "bad request body"}, code=body_status)
            return
        try:
            payload = json.loads(body or b"{}")
        except (ValueError, UnicodeDecodeError):
            self._json({"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "parse error"}},
                       code=400)
            return
        self._json(a2a.handle(payload, run=_a2a_run))

    def _drain_body(self) -> None:
        """Consume request bytes already in the socket before an early refusal.

        Closing a connection with unread request bytes in the receive buffer
        makes Windows send RST, and the client reads WinError 10053 instead of
        the 403/404 it was owed. Draining fixes that -- but it must never become
        an obligation: a client that DECLARES 64 KB and sends nothing must not
        hold this thread. So the read runs under a short socket timeout and
        abandons the moment bytes stop arriving. An honest client's body is
        already buffered and drains instantly; a liar costs half a second, once.

        This deliberately does not call _read_body: the security contract is
        that an untrusted request's body is never READ into memory before
        authentication, and these bytes go nowhere -- they are discarded so the
        socket can close cleanly.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if not 0 < length <= MAX_POST_BODY_BYTES:
            return
        connection = getattr(self, "connection", None)
        try:
            previous = connection.gettimeout() if connection else None
            if connection:
                connection.settimeout(0.5)
            try:
                remaining = length
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 8192))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            finally:
                if connection:
                    connection.settimeout(previous)
        except (OSError, ValueError):
            pass
    def do_POST(self) -> None:
        if not self._host_ok():
            self._drain_body()
            self._send(403, b"forbidden host", "text/plain")
            return
        if not secrets.compare_digest(self.headers.get("X-Birkin-Token", ""), _TOKEN):
            self._drain_body()
            self._json({"error": "missing or invalid token"}, code=403)
            return
        if self.path == "/a2a":
            self._handle_a2a()
            return
        if self.path != "/api/approvals":
            self._drain_body()
            self._send(404, b"not found", "text/plain")
            return
        body, body_status = self._read_body()
        if body_status != 200:
            message = {408: "request body timeout", 413: "payload too large"}.get(
                body_status, "bad content length"
            )
            self._json({"error": message}, code=body_status)
            return
        try:
            payload = json.loads(body or b"{}")
        except (ValueError, UnicodeDecodeError):
            self._json({"error": "bad json"}, code=400)
            return
        if not isinstance(payload, dict):
            self._json({"error": "expected JSON object"}, code=400)
            return
        aid = payload.get("id")
        action = payload.get("action")
        if not aid or action not in ("approve", "reject"):
            self._json({"error": "need id and action approve|reject"}, code=400)
            return
        if not isinstance(aid, str) or _APPROVAL_ID_RE.fullmatch(aid) is None:
            self._json({"error": "invalid approval id"}, code=400)
            return
        result = approvals.approve(aid) if action == "approve" else approvals.reject(aid)
        self._json(result)


def _a2a_run(text: str) -> str:
    """Answer a peer's task with a one-shot birkin turn.

    Deliberately one-shot rather than the warm gateway session: a peer's
    task must not land in, or disturb, a human conversation already in
    progress.
    """
    from ..runtime import build_session
    return build_session().ask(text)


def run(port: Optional[int] = None, *, open_browser: bool = True) -> int:
    cfg = config.load_config()
    port = port or int(cfg.get("web_port", 8787))
    httpd = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"birkin dashboard running at {url}  (Ctrl-C to stop)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        httpd.server_close()
    return 0