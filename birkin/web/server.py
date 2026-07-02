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
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Optional

from .. import approvals, config, cron, store
from ..skills import build_manager

_STATIC = Path(__file__).resolve().parent / "static"

# A per-process token embedded in the page and required on mutating POSTs.
# Combined with a Host-header check this blocks DNS-rebinding and other local
# processes from approving queued actions.
_TOKEN = secrets.token_urlsafe(18)
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


def _status_payload() -> dict[str, Any]:
    cfg = config.load_config()
    try:
        skills_count = len(build_manager(cfg).skills)
    except Exception:
        skills_count = 0
    from . import server as _self  # noqa: F401 (for clarity)
    from .. import budget as budget_mod
    st = store.read_status()
    stale = store.is_status_stale(st)
    return {
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
        "pending_count": len(store.list_pending()),
        "heartbeat": st.get("heartbeat"),
        "budget": budget_mod.status(cfg),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "birkin-dashboard/0.1"

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
            items = risk_mod.sort_by_risk(store.list_pending())
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
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if not self._host_ok():
            self._send(403, b"forbidden host", "text/plain")
            return
        if not secrets.compare_digest(self.headers.get("X-Birkin-Token", ""), _TOKEN):
            self._json({"error": "missing or invalid token"}, code=403)
            return
        if self.path != "/api/approvals":
            self._send(404, b"not found", "text/plain")
            return
        # int() must be inside the try: a non-numeric Content-Length would
        # otherwise raise ValueError outside it and reset the connection.
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length > 1_000_000:
                self._json({"error": "payload too large"}, code=413)
                return
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, UnicodeDecodeError):
            self._json({"error": "bad json"}, code=400)
            return
        aid = payload.get("id")
        action = payload.get("action")
        if not aid or action not in ("approve", "reject"):
            self._json({"error": "need id and action approve|reject"}, code=400)
            return
        result = approvals.approve(aid) if action == "approve" else approvals.reject(aid)
        self._json(result)


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
