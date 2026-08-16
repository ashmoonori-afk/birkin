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
import os
import re
import secrets
import signal
import webbrowser
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import RLock
from types import FrameType
from typing import Any, cast
from weakref import WeakKeyDictionary

from .. import __version__, approvals, config, cron, store
from ..skills import build_manager
from .browser_aside_api import (
    BrowserApiResponse,
    is_browser_path,
)
from .browser_aside_api import (
    close_service as close_browser_service,
)
from .browser_aside_api import (
    delete as delete_browser,
)
from .browser_aside_api import (
    get as get_browser,
)
from .browser_aside_api import (
    post as post_browser,
)
from .browser_aside_workspace import (
    BrowserApiWorkspace,
    browser_api_workspace,
)
from .browser_security import (
    BrowserRequestDenied,
    BrowserRequestGuard,
    browser_request_guard,
)

_STATIC = Path(__file__).resolve().parent / "static"
MAX_POST_BODY_BYTES = 65_536
POST_BODY_TIMEOUT_SECONDS = 2.0
_APPROVAL_ID_RE = re.compile(r"[0-9a-f]{12}")

# A per-process capability set as an HttpOnly cookie on the root page and
# required for sensitive reads and mutations. JavaScript never receives it.
_CAPABILITY_TOKEN = secrets.token_urlsafe(24)
# Compatibility name for trusted local header clients. This is the process
# capability, never a listener bootstrap nonce.
_TOKEN = _CAPABILITY_TOKEN
_CAPABILITY_COOKIE = "birkin_capability"
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
_SECURITY_LOCK = RLock()
_SECURITY_GUARDS: WeakKeyDictionary[object, BrowserRequestGuard] = (
    WeakKeyDictionary()
)
_BOOTSTRAP_NONCES: WeakKeyDictionary[object, str] = WeakKeyDictionary()
_BROWSER_WORKSPACES: WeakKeyDictionary[
    object,
    BrowserApiWorkspace,
] = WeakKeyDictionary()


def workspace_contract() -> dict[str, object]:
    """Return Python-owned state and shared workspace theme contracts."""
    from .. import ui_tokens, uistate, workspace_theme

    return {
        "uistate": uistate.schema(),
        "tokens": ui_tokens.to_json(),
        "workspace_theme": workspace_theme.contract(),
    }


def _browser_guard(server: object, port: int) -> BrowserRequestGuard:
    del port
    with _SECURITY_LOCK:
        guard = _SECURITY_GUARDS.get(server)
        if guard is None:
            _ = _bootstrap_nonce(server)
            guard = _SECURITY_GUARDS.get(server)
        if guard is None:
            raise RuntimeError(
                "listener browser security was not initialized"
            )
        return guard


def _bootstrap_nonce(server: object) -> str:
    with _SECURITY_LOCK:
        nonce = _BOOTSTRAP_NONCES.get(server)
        if nonce is None:
            nonce = secrets.token_urlsafe(24)
            _BOOTSTRAP_NONCES[server] = nonce
            address = cast(
                tuple[str, int],
                cast(HTTPServer, server).server_address,
            )
            _SECURITY_GUARDS[server] = browser_request_guard(
                port=address[1],
                capability=_CAPABILITY_TOKEN,
                bootstrap_nonce=nonce,
            )
        return nonce


def listener_bootstrap_nonce(server: object) -> str:
    return _bootstrap_nonce(server)


def _browser_workspace(server: object) -> BrowserApiWorkspace:
    with _SECURITY_LOCK:
        workspace = _BROWSER_WORKSPACES.get(server)
        if workspace is None:
            workspace = browser_api_workspace(
                f"web:{_bootstrap_nonce(server)}"
            )
            _BROWSER_WORKSPACES[server] = workspace
        return workspace


def bootstrap_nonce_for_port(port: int) -> str:
    with _SECURITY_LOCK:
        for server, nonce in _BOOTSTRAP_NONCES.items():
            address = cast(
                tuple[str, int],
                cast(HTTPServer, server).server_address,
            )
            if address[1] == port:
                return nonce
    raise LookupError("listener bootstrap nonce is unavailable")


def _checkpoint_manager():
    from ..checkpoints import CheckpointManager
    cfg = config.load_config()
    return CheckpointManager(enabled=bool(cfg.get("checkpoints", True)))


def _status_payload() -> dict[str, Any]:
    cfg = config.load_config()
    skills_error = None
    try:
        skills_count = len(build_manager(cfg).skills)
    except (OSError, RuntimeError, TypeError, ValueError):
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
        "morpheus_hour": cfg.get("morpheus_hour", cfg.get("nightly_hour", 7)),
        "nightly_hour": cfg.get("morpheus_hour", cfg.get("nightly_hour", 7)),
        "pending_count": len(approvals.reviewable_pending()),
        "heartbeat": st.get("heartbeat"),
        "budget": budget_mod.status(cfg),
    }
    if skills_error:
        payload["skills_error"] = skills_error
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = f"birkin-dashboard/{__version__}"

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send(
        self,
        code: int,
        body: bytes,
        ctype: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "base-uri 'none'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "img-src 'self' blob:; "
            "object-src 'none'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'",
        )
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _browser_response(
        self,
        response: BrowserApiResponse,
    ) -> None:
        payload = response.payload
        if isinstance(payload, dict):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(
                response.status,
                body,
                "application/json; charset=utf-8",
                response.headers,
            )
        elif isinstance(payload, bytes):
            self._send(
                response.status,
                payload,
                response.content_type,
                response.headers,
            )
        else:
            self._send(
                response.status,
                b"",
                response.content_type,
                response.headers,
            )

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host", "") or "").rsplit(":", 1)[0]
        return host in _ALLOWED_HOSTS or host == ""

    def _capability_ok(self) -> bool:
        token = self.headers.get("X-Birkin-Token", "")
        if token:
            return secrets.compare_digest(token, _CAPABILITY_TOKEN)
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except CookieError:
            return False
        capability = cookies.get(_CAPABILITY_COOKIE)
        if capability is None:
            return False
        return secrets.compare_digest(
            capability.value,
            _CAPABILITY_TOKEN,
        )

    def _browser_denial(
        self,
        method: str,
    ) -> BrowserRequestDenied | None:
        client_id = self.headers.get("X-Birkin-Browser-Client", "")
        if (
            not 8 <= len(client_id) <= 80
            or not all(
                character.isalnum() or character in {"-", "_"}
                for character in client_id
            )
        ):
            return BrowserRequestDenied(
                "client_identity_denied",
                "Browser client identity is missing or invalid.",
            )
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except CookieError:
            cookies = SimpleCookie()
        morsel = cookies.get(_CAPABILITY_COOKIE)
        server_port = cast(HTTPServer, self.server).server_port
        content_type = self.headers.get("Content-Type")
        if content_type is not None:
            content_type = content_type.split(";", maxsplit=1)[0].strip()
        try:
            _browser_guard(self.server, server_port).authorize(
                method=method,
                path=self.path,
                host=self.headers.get("Host", ""),
                origin=self.headers.get("Origin"),
                fetch_site=self.headers.get("Sec-Fetch-Site"),
                content_type=content_type,
                cookie_capability=morsel.value if morsel else None,
                header_capability=self.headers.get("X-Birkin-Token"),
            )
        except BrowserRequestDenied as exc:
            return exc
        return None

    def _browser_actor_id(self) -> str:
        return (
            "human:web:"
            + self.headers["X-Birkin-Browser-Client"]
        )

    def _send_browser_denial(
        self,
        denial: BrowserRequestDenied,
    ) -> None:
        self._json(
            {
                "error": {
                    "code": denial.code,
                    "message": denial.safe_message,
                }
            },
            code=denial.status,
        )

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
        if is_browser_path(self.path):
            denial = self._browser_denial("GET")
            if denial is not None:
                self._send_browser_denial(denial)
                return
            self._browser_response(get_browser(
                self.path,
                actor_id=self._browser_actor_id(),
                workspace=_browser_workspace(self.server),
            ))
            return
        if self.path.startswith("/_bootstrap/"):
            nonce = self.path.removeprefix("/_bootstrap/")
            try:
                capability = _browser_guard(
                    self.server,
                    cast(HTTPServer, self.server).server_port,
                ).consume_bootstrap(
                    nonce,
                    host=self.headers.get("Host", ""),
                )
            except BrowserRequestDenied as exc:
                self._send_browser_denial(exc)
                return
            self._send(
                303,
                b"",
                "text/plain",
                headers={
                    "Location": "/",
                    "Set-Cookie": (
                        f"{_CAPABILITY_COOKIE}={capability}; HttpOnly; "
                        "SameSite=Strict; Path=/"
                    ),
                },
            )
        elif self.path in ("/", "/index.html"):
            html = (_STATIC / "index.html").read_text(encoding="utf-8")
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._json(_status_payload())
        elif self.path.startswith("/api/approvals/") and self.path.endswith("/diff"):
            if not self._capability_ok():
                self._json({"error": "missing or invalid capability"}, code=403)
                return
            from .. import ide
            approval_id = self.path.split("/")[3]
            code, text = ide.approval_diff(approval_id)
            if code != 200:
                self._json({"error": "diff unavailable"}, code=code)
                return
            self._send(200, text.encode("utf-8"), "text/x-diff; charset=utf-8")
        elif self.path == "/api/config":
            if not self._capability_ok():
                self._json({"error": "missing or invalid capability"}, code=403)
                return
            from .. import ide
            self._json(ide.safe_config())
        elif self.path.startswith("/api/checkpoints"):
            if not self._capability_ok():
                self._json({"error": "missing or invalid capability"}, code=403)
                return
            from urllib.parse import urlsplit

            from .. import ide
            workspace = ide.workspace_from_path(self.path)
            route = urlsplit(self.path).path
            manager = _checkpoint_manager()
            diff_match = re.fullmatch(
                r"/api/checkpoints/([0-9a-fA-F]{4,40})/diff", route)
            if route == "/api/checkpoints":
                self._json(manager.list_checkpoints(workspace))
            elif route == "/api/checkpoints/timeline":
                self._json(manager.timeline(workspace))
            elif route == "/api/checkpoints/lineage":
                self._json(manager.lineage(workspace))
            elif diff_match:
                self._json(manager.diff_preview(workspace, diff_match.group(1)))
            else:
                self._json({"error": "checkpoint route not found"}, code=404)
        elif self.path == "/api/events":
            if not self._capability_ok():
                self._json({"error": "missing or invalid capability"}, code=403)
                return
            from .. import ide
            body = ("event: snapshot\n" + "data: "
                    + json.dumps(ide.event_snapshot(), ensure_ascii=False)
                    + "\n\n").encode("utf-8")
            self._send(200, body, "text/event-stream")
        elif self.path == "/api/contract":
            # Python-owned UI contract: state schema + design tokens. The
            # page generates its state table from this; it never copies it.
            # A broken export is a 500, never a dead server: presentation
            # failures must not take the daemon down.
            try:
                payload = workspace_contract()
            except (OSError, RuntimeError, TypeError, ValueError):
                self._json({"error": "contract unavailable"}, code=500)
                return
            self._json(payload)
        elif self.path == "/api/jobs":
            from .. import uistate
            jobs = cron.load_jobs()
            for job in jobs:
                job["ui_state"] = uistate.from_cron(
                    enabled=bool(job.get("enabled", True)),
                ).state
            self._json({"status": store.read_status(), "jobs": jobs})
        elif self.path == "/api/runs":
            from .. import uistate
            runs = store.list_runs(limit=20)
            for run in runs:
                run["ui_state"] = uistate.from_recent_run(run).state
            self._json(runs)
        elif self.path == "/api/approvals":
            if not self._capability_ok():
                self._json({"error": "missing or invalid capability"}, code=403)
                return
            from .. import risk as risk_mod
            from .. import uistate
            items = risk_mod.sort_by_risk(approvals.reviewable_pending())
            for it in items:
                it["risk"] = risk_mod.risk_for(it.get("category", ""))
                it["ui_state"] = uistate.from_approval(it).state
            self._json(items)
        elif self.path == "/api/skills":
            cfg = config.load_config()
            try:
                mgr = build_manager(cfg)
                self._json([{"name": s.name, "description": s.description,
                             "source": s.source}
                            for s in sorted(mgr.skills.values(), key=lambda x: x.name)])
            except (OSError, RuntimeError, TypeError, ValueError):
                self._json({"error": "skills unavailable"}, code=500)
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
        if is_browser_path(self.path):
            if not self._host_ok():
                self._send(403, b"forbidden host", "text/plain")
                return
            if not self._capability_ok():
                self._json(
                    {"error": "missing or invalid token"},
                    code=403,
                )
                return
            denial = self._browser_denial("POST")
            if denial is not None:
                self._send_browser_denial(denial)
                return
            body, body_status = self._read_body()
            if body is None:
                self._json(
                    {"error": {"code": "invalid_request"}},
                    code=body_status,
                )
                return
            self._browser_response(
                post_browser(
                    self.path,
                    body,
                    actor_id=self._browser_actor_id(),
                    workspace=_browser_workspace(self.server),
                )
            )
            return
        if not self._host_ok():
            self._drain_body()
            self._send(403, b"forbidden host", "text/plain")
            return
        if not self._capability_ok():
            self._drain_body()
            self._json({"error": "missing or invalid token"}, code=403)
            return
        if self.path == "/a2a":
            self._handle_a2a()
            return
        is_context = self.path == "/api/context"
        checkpoint_match = re.fullmatch(
            r"/api/checkpoints/([0-9a-fA-F]{4,40})/(restore|fork)", self.path)
        if (self.path.startswith("/api/checkpoints/")
                and self.path.rsplit("/", 1)[-1] in {"restore", "fork"}
                and not checkpoint_match):
            self._drain_body()
            self._json({"error": "invalid checkpoint id"}, code=400)
            return
        if self.path != "/api/approvals" and not is_context and not checkpoint_match:
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
        if is_context:
            from .. import ide
            if not ide.save_context(payload):
                self._json({"error": "invalid editor context"}, code=400)
                return
            self._json({"ok": True})
            return
        if checkpoint_match:
            workspace = Path(str(payload.get("workspace") or Path.cwd())).expanduser().resolve()
            checkpoint = checkpoint_match.group(1)
            action = checkpoint_match.group(2)
            if action == "restore":
                from ..checkpoints import RestoreMode
                try:
                    mode = RestoreMode(str(payload.get("mode") or ""))
                except ValueError:
                    self._json({"error": "mode must be files, task, or both"}, code=400)
                    return
                proposal = approvals.propose(
                    category="checkpoint_restore",
                    title=f"Restore checkpoint {checkpoint[:7]}",
                    description=(
                        f"Restore {mode.value} for {workspace}. "
                        "This destructive action is undo-checkpointed before execution."
                    ),
                    payload={"workspace": str(workspace), "checkpoint": checkpoint,
                             "mode": mode.value},
                    cfg=config.load_config(), origin="web:checkpoints",
                )
                self._json({"ok": True, "approval_required": True,
                            "approval_id": proposal["id"], "mode": mode.value}, code=202)
                return
            command = payload.get("command")
            if (not isinstance(command, list) or not command
                    or not all(isinstance(item, str) and item for item in command)):
                self._json({"error": "command must be a non-empty string array"}, code=400)
                return
            from ..sandbox import load_repo_sandbox
            spec = load_repo_sandbox(workspace)
            try:
                result = _checkpoint_manager().fork(
                    workspace, checkpoint, command, policy=spec.policy)
            except (OSError, RuntimeError, TypeError, ValueError):
                self._json({"error": "checkpoint fork failed"}, code=409)
                return
            self._json({"ok": True, "returncode": result.returncode,
                        "stdout": result.stdout, "stderr": result.stderr},
                       code=200 if result.returncode == 0 else 409)
            return
        aid = payload.get("id")
        action = payload.get("action")
        if not aid or action not in ("answer", "approve", "reject"):
            self._json(
                {"error": "need id and action answer|approve|reject"},
                code=400,
            )
            return
        if not isinstance(aid, str) or _APPROVAL_ID_RE.fullmatch(aid) is None:
            self._json({"error": "invalid approval id"}, code=400)
            return
        if action == "answer":
            answers = payload.get("answers")
            if not isinstance(answers, dict):
                self._json({"error": "answers must be an object"}, code=400)
                return
            result = approvals.answer(
                aid,
                answers=answers,
                source="web:dashboard",
                clarification=str(payload.get("clarification") or ""),
                navigation=payload.get("navigation")
                if isinstance(payload.get("navigation"), list) else None,
                capability="dashboard.approvals.answer.v1",
                resume_token=str(payload.get("resume_token") or ""),
                question_digest=str(payload.get("question_digest") or ""),
                input_schema_version=payload.get("input_schema_version")
                if isinstance(payload.get("input_schema_version"), int)
                and not isinstance(payload.get("input_schema_version"), bool)
                else None,
                previous_state_digest=str(
                    payload.get("previous_state_digest") or ""
                ),
            )
            self._json(result, code=200 if result.get("ok") else 409)
            return
        result = (
            approvals.approve(aid)
            if action == "approve"
            else approvals.reject(aid)
        )
        self._json(result)

    def do_DELETE(self) -> None:
        if not self._host_ok():
            self._send(403, b"forbidden host", "text/plain")
            return
        if not is_browser_path(self.path):
            self._json({"error": "not found"}, code=404)
            return
        denial = self._browser_denial("DELETE")
        if denial is not None:
            self._send_browser_denial(denial)
            return
        self._browser_response(delete_browser(
            self.path,
            actor_id=self._browser_actor_id(),
            workspace=_browser_workspace(self.server),
        ))

    def do_OPTIONS(self) -> None:
        if not is_browser_path(self.path):
            self._json({"error": "not found"}, code=404)
            return
        denial = self._browser_denial("OPTIONS")
        if denial is not None:
            self._send_browser_denial(denial)
            return
        self._json({"error": "not found"}, code=404)


def _a2a_run(text: str) -> str:
    """Answer a peer's task with a one-shot birkin turn.

    Deliberately one-shot rather than the warm gateway session: a peer's
    task must not land in, or disturb, a human conversation already in
    progress.
    """
    from ..runtime import build_session
    return build_session().ask(text)


def run(port: int | None = None, *, open_browser: bool = True) -> int:
    from ..moirai import continuation

    continuation.recover()
    cfg = config.load_config()
    port = port or int(cfg.get("web_port", 8787))
    httpd = HTTPServer(("127.0.0.1", port), Handler)
    server_address = cast(tuple[str, int], httpd.server_address)
    actual_port = server_address[1]
    bootstrap_nonce = _bootstrap_nonce(httpd)
    os.environ["BIRKIN_BROWSER_CONTROL_ADDRESSES"] = (
        f"127.0.0.1:{actual_port},localhost:{actual_port}"
    )
    session_path = config.birkin_home() / "web_session.json"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    store._write_json(
        session_path,
        {"port": actual_port, "token": _CAPABILITY_TOKEN},
    )
    url = f"http://127.0.0.1:{actual_port}"
    bootstrap_url = f"{url}/_bootstrap/{bootstrap_nonce}"
    print(f"birkin dashboard running at {bootstrap_url}  (Ctrl-C to stop)")
    if open_browser:
        try:
            _ = webbrowser.open(bootstrap_url)
        except (OSError, webbrowser.Error):
            print("could not open the dashboard URL automatically")
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def stop_on_sigterm(
        _signum: int,
        _frame: FrameType | None,
    ) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_on_sigterm)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        try:
            _ = close_browser_service(
                workspace=_browser_workspace(httpd)
            )
        finally:
            try:
                session_path.unlink(missing_ok=True)
            finally:
                httpd.server_close()
    return 0
