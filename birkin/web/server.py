"""Birkin chat workspace and control APIs on a standard-library HTTP server.

Endpoints:
- ``GET  /``              -> responsive chat workspace
- ``/api/workspace/*``    -> durable sessions, snapshots, commands, and SSE
- ``GET  /api/status``    -> model, vault, skills, daemon, next Morpheus, counts
- ``GET  /api/jobs``      -> scheduled cron jobs + daemon heartbeat
- ``GET  /api/runs``      -> recent Morpheus / cron run summaries
- ``GET  /api/approvals`` -> pending proposed actions
- ``POST /api/approvals`` -> {id, action: "approve"|"reject"}
- ``GET  /api/skills``    -> skill catalog

The static root is local-only. Sensitive control and workspace routes require
the loopback capability established by the private bootstrap URL.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import signal
import socket
import sys
import threading
import webbrowser
from collections.abc import Mapping
from dataclasses import replace
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from types import FrameType
from typing import Any, cast, final
from typing_extensions import assert_never
from urllib.parse import parse_qs, urlsplit
from weakref import WeakKeyDictionary

from .. import __version__, approvals, config, cron, store
from ..browser_aside_control import browser_workspace_registry
from ..browser_aside_errors import BrowserAsideError
from ..runtime import Session
from ..skills import build_manager
from ..workspace import (
    CommandIdConflict,
    ProtocolError,
    StaleCursor,
    WorkspaceCommand,
    WorkspaceHub,
    WorkspaceSession,
    WorkspaceSnapshot,
)
from ..workspace.hub import EventSink
from ..workspace.runtime_adapter import RuntimeWorkspaceAdapter
from ..workspace.service import CommandHandler
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
from .external_origin import (
    WebExternalOrigin,
    parse_web_external_url,
)
from .request_payload import (
    JSONValue,
    RequestPayloadError,
    parse_object,
    string_list,
)
from .routes import GetRoute, PostRoute, RouteMatch, match_get, match_post

_STATIC = Path(__file__).resolve().parent / "static"
MAX_POST_BODY_BYTES = 65_536
POST_BODY_TIMEOUT_SECONDS = 2.0
MAX_PUBLIC_WORKERS = 4
PUBLIC_HEADER_TIMEOUT_SECONDS = 5.0
REJECTED_HEADER_TIMEOUT_SECONDS = 0.5
MAX_REJECTED_HEADER_BYTES = 16_384
_APPROVAL_ID_RE = re.compile(r"[0-9a-f]{12}")


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler: type[BaseHTTPRequestHandler],
        bind_and_activate: bool = True,
    ) -> None:
        self._worker_slots = threading.BoundedSemaphore(MAX_PUBLIC_WORKERS)
        super().__init__(
            server_address,
            request_handler,
            bind_and_activate,
        )

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(PUBLIC_HEADER_TIMEOUT_SECONDS)
        return request, address

    def process_request(
        self,
        request: Any,
        client_address: Any,
    ) -> None:
        if not self._worker_slots.acquire(blocking=False):
            self._drain_rejected_request(cast(socket.socket, request))
            try:
                cast(socket.socket, request).sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Type: text/plain; charset=utf-8\r\n"
                    b"Content-Length: 12\r\n"
                    b"Connection: close\r\n\r\n"
                    b"server busy\n"
                )
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._worker_slots.release()
            raise

    @staticmethod
    def _drain_rejected_request(request: socket.socket) -> None:
        previous_timeout = request.gettimeout()
        remaining = MAX_REJECTED_HEADER_BYTES
        suffix = b""
        try:
            request.settimeout(REJECTED_HEADER_TIMEOUT_SECONDS)
            while remaining > 0:
                pending = request.recv(
                    min(remaining, 4096),
                    socket.MSG_PEEK,
                )
                if not pending:
                    return
                combined = suffix + pending
                boundary = combined.find(b"\r\n\r\n")
                consume = boundary + 4 - len(suffix) if boundary >= 0 else len(pending)
                consumed = 0
                while consumed < consume:
                    chunk = request.recv(consume - consumed)
                    if not chunk:
                        return
                    consumed += len(chunk)
                remaining -= consumed
                if boundary >= 0:
                    return
                suffix = combined[-3:]
        except OSError:
            return
        finally:
            request.settimeout(previous_timeout)

    def process_request_thread(
        self,
        request: Any,
        client_address: Any,
    ) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._worker_slots.release()


HTTPServer = BoundedHTTPServer

# A per-process capability set as an HttpOnly cookie on the root page and
# required for sensitive reads and mutations. JavaScript never receives it.
_CAPABILITY_TOKEN = os.environ.get("BIRKIN_HTTP_TOKEN") or secrets.token_urlsafe(24)
# Compatibility name for trusted local header clients. This is the process
# capability, never a listener bootstrap nonce.
_TOKEN = _CAPABILITY_TOKEN
_CAPABILITY_COOKIE = "birkin_capability"
_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAPPED_SERVERS: WeakKeyDictionary[object, bool] = WeakKeyDictionary()
_workspace_stream_slots = threading.BoundedSemaphore(32)
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
_LOOPBACK_PEERS = {"127.0.0.1", "::1"}
_workspace_root: Path | None = None
_workspace_handlers: Mapping[str, CommandHandler] | None = None
_workspace_hub: WorkspaceHub | None = None
_workspace_lock = threading.Lock()
_workspace_adapters: dict[str, RuntimeWorkspaceAdapter] = {}
_SECURITY_LOCK = RLock()
_SECURITY_GUARDS: WeakKeyDictionary[object, BrowserRequestGuard] = WeakKeyDictionary()
_BOOTSTRAP_NONCES: WeakKeyDictionary[object, str] = WeakKeyDictionary()
_BROWSER_WORKSPACES: WeakKeyDictionary[
    object,
    BrowserApiWorkspace,
] = WeakKeyDictionary()
_EXTERNAL_ORIGINS: WeakKeyDictionary[
    object,
    WebExternalOrigin | None,
] = WeakKeyDictionary()
_REMOTE_ADMISSION: WeakKeyDictionary[object, bool] = WeakKeyDictionary()


def _consume_bootstrap(server: object) -> bool:
    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAPPED_SERVERS.get(server, False):
            return False
        _BOOTSTRAPPED_SERVERS[server] = True
        return True


def capability_token() -> str:
    """Return the in-process token for trusted local client adapters."""
    return _TOKEN


def workspace_contract() -> dict[str, object]:
    """Return the Python-owned state and shared workspace theme contracts."""
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
            raise RuntimeError("listener browser security was not initialized")
        return guard


def _listener_external_origin(
    server: object,
) -> WebExternalOrigin | None:
    with _SECURITY_LOCK:
        if server not in _EXTERNAL_ORIGINS:
            _EXTERNAL_ORIGINS[server] = parse_web_external_url(
                config.load_config().get("web_external_url", "")
            )
        return _EXTERNAL_ORIGINS[server]


def _set_listener_external_origin(
    server: object,
    external_origin: WebExternalOrigin | None,
) -> None:
    with _SECURITY_LOCK:
        _EXTERNAL_ORIGINS[server] = external_origin


def _listener_remote_access(server: object) -> bool:
    with _SECURITY_LOCK:
        if server not in _REMOTE_ADMISSION:
            _REMOTE_ADMISSION[server] = bool(
                config.load_config().get("web_remote_access", False)
            )
        return _REMOTE_ADMISSION[server]


def _set_listener_remote_access(
    server: object,
    remote: bool,
) -> None:
    with _SECURITY_LOCK:
        _REMOTE_ADMISSION[server] = remote


def _bootstrap_nonce(server: object) -> str:
    with _SECURITY_LOCK:
        nonce = _BOOTSTRAP_NONCES.get(server)
        if nonce is None:
            nonce = secrets.token_urlsafe(24)
            _BOOTSTRAP_NONCES[server] = nonce
            _ = _listener_remote_access(server)
            address = cast(
                tuple[str, int],
                cast(HTTPServer, server).server_address,
            )
            _SECURITY_GUARDS[server] = browser_request_guard(
                port=address[1],
                capability=_CAPABILITY_TOKEN,
                bootstrap_nonce=nonce,
                external_origin=(
                    external.origin
                    if (external := _listener_external_origin(server))
                    else None
                ),
            )
        return nonce


def listener_bootstrap_nonce(server: object) -> str:
    return _bootstrap_nonce(server)


def _browser_workspace(server: object) -> BrowserApiWorkspace:
    with _SECURITY_LOCK:
        workspace = _BROWSER_WORKSPACES.get(server)
        if workspace is None:
            workspace = browser_api_workspace(f"web:{_bootstrap_nonce(server)}")
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


def _get_workspace_hub() -> WorkspaceHub:
    global _workspace_hub
    with _workspace_lock:
        if _workspace_hub is None:
            root = _workspace_root or (config.birkin_home() / "workspace")
            if _workspace_handlers is not None:
                _workspace_hub = WorkspaceHub(
                    root=root,
                    handlers=_workspace_handlers,
                )
            else:

                def factory(
                    session_id: str,
                    emit: EventSink,
                ) -> Mapping[str, CommandHandler]:
                    adapter = RuntimeWorkspaceAdapter(session_id, emit)
                    _workspace_adapters[session_id] = adapter
                    return adapter.handlers()

                _workspace_hub = WorkspaceHub(
                    root=root,
                    handler_factory=factory,
                )
    return _workspace_hub


def workspace_runtime(session_id: str) -> tuple[WorkspaceSession, Session]:
    session, _ = _get_workspace_hub().create(session_id)
    adapter = _workspace_adapters.get(session_id)
    if adapter is None:
        raise RuntimeError("workspace runtime adapter is unavailable")
    return session, adapter.runtime_session()


def workspace_snapshot(session_id: str) -> WorkspaceSnapshot:
    session = _get_workspace_hub().get(session_id)
    if session is None:
        raise ProtocolError("workspace session not found")
    snapshot = session.snapshot()
    adapter = _workspace_adapters.get(session_id)
    enrich = getattr(adapter, "enrich_snapshot", None)
    if callable(enrich):
        return cast(WorkspaceSnapshot, enrich(snapshot))
    return snapshot


def signal_workspace_interrupt(session_id: str) -> bool:
    adapter = _workspace_adapters.get(session_id)
    if adapter is None:
        return False
    adapter.interrupt_now()
    return True


def _close_workspace_runtime() -> None:
    global _workspace_hub
    for adapter in _workspace_adapters.values():
        adapter.close()
    _workspace_adapters.clear()
    if _workspace_hub is not None:
        _workspace_hub.close()
        _workspace_hub = None


@final
class BackgroundWebServer:
    def __init__(
        self,
        httpd: HTTPServer,
        thread: threading.Thread,
        session_path: Path | None,
        bootstrap_url: str,
    ) -> None:
        self.httpd = httpd
        self.thread = thread
        self.session_path = session_path
        self.bootstrap_url = bootstrap_url
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _close_workspace_runtime()
        _ = close_browser_service(workspace=_browser_workspace(self.httpd))
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        if self.session_path is not None and self.session_path.is_file():
            self.session_path.unlink()


def start_background(port: int | None = None) -> BackgroundWebServer:
    cfg = config.load_config()
    configured_port = cast(object, cfg.get("web_port", 8787))
    if not isinstance(configured_port, (int, str)):
        raise TypeError("web_port must be an integer")
    selected_port = port if port is not None else int(configured_port)
    try:
        httpd = HTTPServer(("127.0.0.1", selected_port), Handler)
    except OSError:
        if selected_port == 0:
            raise
        httpd = HTTPServer(("127.0.0.1", 0), Handler)
    address = cast(tuple[str, int], httpd.server_address)
    actual_port = address[1]
    _set_listener_external_origin(httpd, None)
    _set_listener_remote_access(httpd, False)
    bootstrap_nonce = _bootstrap_nonce(httpd)
    os.environ["BIRKIN_BROWSER_CONTROL_ADDRESSES"] = (
        f"127.0.0.1:{actual_port},localhost:{actual_port}"
    )
    bootstrap_url = f"http://127.0.0.1:{actual_port}/_bootstrap/{bootstrap_nonce}"
    thread = threading.Thread(
        target=httpd.serve_forever,
        name="birkin-workspace-web",
        daemon=True,
    )
    thread.start()
    return BackgroundWebServer(httpd, thread, None, bootstrap_url)


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
    server: BoundedHTTPServer
    server_version = f"birkin-dashboard/{__version__}"
    protocol_version: str = "HTTP/1.1"

    def handle(self) -> None:
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            return

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
        self._send(
            code,
            json.dumps(obj, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

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

    def _workspace_stream(
        self,
        session: WorkspaceSession,
        *,
        after: int,
        until: str | None,
    ) -> None:
        if not _workspace_stream_slots.acquire(blocking=False):
            self._json(
                {"error": "workspace stream capacity reached"},
                code=503,
            )
            return
        try:
            self._workspace_stream_open(
                session,
                after=after,
                until=until,
            )
        finally:
            _workspace_stream_slots.release()

    def _workspace_stream_open(
        self,
        session: WorkspaceSession,
        *,
        after: int,
        until: str | None,
    ) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "keep-alive")
        self.close_connection = True
        self.end_headers()
        self.wfile.flush()
        cursor = after
        try:
            while True:
                events = session.wait_events(
                    after=cursor,
                    until=None,
                    timeout=2.0,
                )
                if session.closed:
                    return
                if events:
                    chunks = [
                        (
                            f"id: {event.cursor}\n"
                            f"event: {event.type}\n"
                            "data: "
                            f"{json.dumps(event.to_json(), ensure_ascii=False)}"
                            "\n\n"
                        )
                        for event in events
                    ]
                    cursor = events[-1].cursor
                    body = "".join(chunks).encode("utf-8")
                else:
                    body = b": heartbeat\n\n"
                _ = self.wfile.write(body)
                self.wfile.flush()
                if until is not None and any(event.type == until for event in events):
                    return
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _workspace_get(self) -> bool:
        parsed = urlsplit(self.path)
        path = parsed.path
        if not path.startswith("/api/workspace/"):
            return False
        if not self._capability_ok():
            self._json({"error": "missing or invalid capability"}, code=403)
            return True
        if not self._cookie_origin_ok(write=False):
            self._json({"error": "cross-origin capability request"}, code=403)
            return True
        hub = _get_workspace_hub()
        if path == "/api/workspace/sessions":
            self._json(hub.summaries())
            return True
        snapshot_match = re.fullmatch(
            r"/api/workspace/sessions/([A-Za-z0-9._:-]{1,128})/snapshot",
            path,
        )
        events_match = re.fullmatch(
            r"/api/workspace/sessions/([A-Za-z0-9._:-]{1,128})/events",
            path,
        )
        if snapshot_match:
            session = hub.get(snapshot_match.group(1))
            if session is None:
                self._json({"error": "workspace session not found"}, code=404)
                return True
            self._json(workspace_snapshot(session.session_id).to_json())
            return True
        if events_match:
            session = hub.get(events_match.group(1))
            if session is None:
                self._json({"error": "workspace session not found"}, code=404)
                return True
            query = parse_qs(parsed.query, keep_blank_values=True)
            try:
                after_text = (query.get("after") or ["0"])[0]
                if not re.fullmatch(r"\d{1,18}", after_text):
                    raise ValueError
                after = int(after_text)
            except (TypeError, ValueError):
                self._json({"error": "after must be a non-negative integer"}, code=400)
                return True
            until = (query.get("until") or [None])[0]
            if until is not None and (re.fullmatch(r"[a-z.]{1,64}", until) is None):
                self._json({"error": "invalid until event type"}, code=400)
                return True
            once = (query.get("once") or ["0"])[0] == "1"
            if not once:
                self._workspace_stream(
                    session,
                    after=after,
                    until=until,
                )
                return True
            events = session.wait_events(
                after=after,
                until=until,
                timeout=2.0,
            )
            chunks: list[str] = []
            for event in events:
                chunks.append(
                    f"id: {event.cursor}\n"
                    + f"event: {event.type}\n"
                    + "data: "
                    + json.dumps(event.to_json(), ensure_ascii=False)
                    + "\n\n"
                )
            self._send(
                200,
                "".join(chunks).encode("utf-8"),
                "text/event-stream; charset=utf-8",
                {"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            )
            return True
        self._json({"error": "workspace route not found"}, code=404)
        return True

    def _workspace_post(self) -> bool:
        path = urlsplit(self.path).path
        if not path.startswith("/api/workspace/"):
            return False
        body, body_status = self._read_body()
        if body_status != 200:
            message = {
                408: "request body timeout",
                413: "payload too large",
            }.get(body_status, "bad content length")
            self._json({"error": message}, code=body_status)
            return True
        try:
            raw_payload = cast(object, json.loads(body or b"{}"))
        except (ValueError, UnicodeDecodeError):
            self._json({"error": "bad json"}, code=400)
            return True
        if not isinstance(raw_payload, dict):
            self._json({"error": "expected JSON object"}, code=400)
            return True
        payload = cast(dict[str, object], raw_payload)
        hub = _get_workspace_hub()
        if path == "/api/workspace/sessions":
            if set(payload) != {"session_id"}:
                self._json({"error": "session_id is required"}, code=400)
                return True
            try:
                session, created = hub.create(str(payload.get("session_id") or ""))
            except ProtocolError as exc:
                self._json({"error": str(exc)}, code=400)
                return True
            self._json(
                {
                    "session_id": session.session_id,
                    "cursor": session.snapshot().cursor,
                },
                code=201 if created else 200,
            )
            return True
        command_match = re.fullmatch(
            r"/api/workspace/sessions/([A-Za-z0-9._:-]{1,128})/commands",
            path,
        )
        if command_match:
            session = hub.get(command_match.group(1))
            if session is None:
                self._json({"error": "workspace session not found"}, code=404)
                return True
            try:
                command = WorkspaceCommand.parse(payload)
                actor = f"web:{command.client_context.view_id}"

                def signal_interrupt() -> None:
                    _ = signal_workspace_interrupt(session.session_id)

                on_accepted = (
                    signal_interrupt if command.type == "chat.interrupt" else None
                )
                try:
                    receipt = session.submit(
                        command,
                        actor_id=actor,
                        on_accepted=on_accepted,
                    )
                except StaleCursor as exc:
                    if command.type != "chat.interrupt":
                        raise
                    receipt = session.submit(
                        replace(
                            command,
                            expected_cursor=exc.current_cursor,
                        ),
                        actor_id=actor,
                        on_accepted=on_accepted,
                    )
            except ProtocolError as exc:
                code = 409 if isinstance(exc, (CommandIdConflict, StaleCursor)) else 400
                self._json({"error": str(exc)}, code=code)
                return True
            self._json(
                receipt.to_public_json(),
                code=200 if receipt.duplicate else 202,
            )
            return True
        self._json({"error": "workspace route not found"}, code=404)
        return True

    def _host_ok(self) -> bool:
        peer = self.client_address[0]
        host = self.headers.get("Host", "") or ""
        server = getattr(self, "server", None)
        if server is None:
            return (
                peer in _LOOPBACK_PEERS
                and host.rsplit(":", 1)[0] in _ALLOWED_HOSTS
            )
        server_port = cast(HTTPServer, server).server_port
        local_hosts = {
            "127.0.0.1",
            "localhost",
            f"127.0.0.1:{server_port}",
            f"localhost:{server_port}",
        }
        external = _listener_external_origin(server)
        normalized_host = host.lower()
        if peer in _LOOPBACK_PEERS and normalized_host in local_hosts:
            return True
        if (
            external is None
            or normalized_host not in external.authorities
            or not _listener_remote_access(server)
        ):
            return False
        if self.path.startswith("/_bootstrap/"):
            nonce = self.path.removeprefix("/_bootstrap/")
            return secrets.compare_digest(
                nonce,
                _bootstrap_nonce(self.server),
            )
        return self._capability_ok()

    def _header_capability_ok(self) -> bool:
        token = self.headers.get("X-Birkin-Token", "")
        if token and secrets.compare_digest(token, _TOKEN):
            return True
        authorization = self.headers.get("Authorization", "")
        scheme, _, bearer = authorization.partition(" ")
        return bool(
            scheme.lower() == "bearer"
            and bearer
            and secrets.compare_digest(bearer, _TOKEN)
        )

    def _cookie_capability_ok(self) -> bool:
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except CookieError:
            return False
        capability = cookies.get(_CAPABILITY_COOKIE)
        return bool(capability and secrets.compare_digest(capability.value, _TOKEN))

    def _browser_denial(
        self,
        method: str,
    ) -> BrowserRequestDenied | None:
        client_id = self.headers.get("X-Birkin-Browser-Client", "")
        if not 8 <= len(client_id) <= 80 or not all(
            character.isalnum() or character in {"-", "_"} for character in client_id
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
        return "human:web:" + self.headers["X-Birkin-Browser-Client"]

    def _approval_actor_id(self) -> str:
        return "principal:web:authenticated-capability"

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

    def _capability_ok(self) -> bool:
        return self._header_capability_ok() or self._cookie_capability_ok()

    def _cookie_origin_ok(self, *, write: bool) -> bool:
        if self._header_capability_ok():
            return True
        if not self._cookie_capability_ok():
            return True
        external = _listener_external_origin(self.server)
        if external is not None:
            expected_origins = frozenset({external.origin})
        else:
            port = cast(HTTPServer, self.server).server_port
            expected_origins = frozenset({
                f"http://127.0.0.1:{port}",
                f"http://localhost:{port}",
            })
        fetch_site = self.headers.get("Sec-Fetch-Site")
        if fetch_site not in (None, "none", "same-origin"):
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in expected_origins:
            return False
        referer = self.headers.get("Referer")
        if referer is not None:
            parsed = urlsplit(referer)
            if (
                f"{parsed.scheme}://{parsed.netloc}"
                not in expected_origins
            ):
                return False
        if write and origin not in expected_origins:
            return False
        return True

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
        if not self._cookie_origin_ok(write=False):
            self._json({"error": "cross-origin capability request"}, code=403)
            return
        route = match_get(self.path)
        get_route = route.route
        match get_route:
            case GetRoute.BROWSER:
                self._handle_browser_get()
            case GetRoute.FAVICON:
                self._send(204, b"", "image/x-icon")
            case GetRoute.LEGACY_UI:
                self._send(
                    308,
                    b"",
                    "text/plain; charset=utf-8",
                    {
                        "Location": "/",
                        "Deprecation": "true",
                        "Link": '</>; rel="successor-version"',
                    },
                )
            case GetRoute.WORKSPACE:
                _ = self._workspace_get()
            case GetRoute.BOOTSTRAP:
                self._handle_bootstrap_get()
            case (
                GetRoute.APPROVAL_DIFF
                | GetRoute.CONFIG
                | GetRoute.AGENT_RUNS
                | GetRoute.AGENT_RUN
                | GetRoute.ACTION_RECEIPT
                | GetRoute.CHECKPOINTS
                | GetRoute.EVENTS
                | GetRoute.APPROVALS
            ):
                self._handle_protected_get(route, get_route)
            case (
                GetRoute.ROOT
                | GetRoute.STATUS
                | GetRoute.CONTRACT
                | GetRoute.JOBS
                | GetRoute.RUNS
                | GetRoute.SKILLS
                | GetRoute.AGENT_CARD
                | GetRoute.NOT_FOUND
            ):
                self._handle_public_get(get_route)
            case _ as unreachable:
                assert_never(unreachable)

    def _handle_browser_get(self) -> None:
        denial = self._browser_denial("GET")
        if denial is not None:
            self._send_browser_denial(denial)
            return
        self._browser_response(
            get_browser(
                self.path,
                actor_id=self._browser_actor_id(),
                workspace=_browser_workspace(self.server),
            )
        )

    def _handle_bootstrap_get(self) -> None:
        nonce = self.path.removeprefix("/_bootstrap/")
        try:
            capability = _browser_guard(
                self.server,
                self.server.server_port,
            ).consume_bootstrap(
                nonce,
                host=self.headers.get("Host", ""),
                allow_remote_host=(self.client_address[0] not in _LOOPBACK_PEERS),
            )
        except BrowserRequestDenied as exc:
            self._send_browser_denial(exc)
            return
        if not _consume_bootstrap(self.server):
            self._send(
                410,
                b"bootstrap capability already consumed",
                "text/plain; charset=utf-8",
            )
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
                    + (
                        "; Secure"
                        if (external := _listener_external_origin(self.server))
                        is not None
                        and external.secure
                        else ""
                    )
                ),
            },
        )

    def _handle_protected_get(
        self,
        route: RouteMatch[GetRoute],
        get_route: GetRoute,
    ) -> None:
        if not self._capability_ok():
            self._json({"error": "missing or invalid capability"}, code=403)
            return
        match get_route:
            case GetRoute.APPROVAL_DIFF:
                from .. import ide

                code, text = ide.approval_diff(route.identifier)
                if code != 200:
                    self._json({"error": "diff unavailable"}, code=code)
                    return
                self._send(200, text.encode("utf-8"), "text/x-diff; charset=utf-8")
            case GetRoute.CONFIG:
                from .. import ide

                self._json(ide.safe_config())
            case GetRoute.AGENT_RUNS:
                from . import approval_console

                self._json(approval_console.list_runs())
            case GetRoute.AGENT_RUN:
                from . import approval_console

                code, payload = approval_console.run_detail(route.identifier)
                self._json(payload, code=code)
            case GetRoute.ACTION_RECEIPT:
                from . import approval_console

                code, payload = approval_console.action_receipt(route.identifier)
                self._json(payload, code=code)
            case GetRoute.CHECKPOINTS:
                self._handle_checkpoint_get()
            case GetRoute.EVENTS:
                from .. import ide

                body = (
                    "event: snapshot\n"
                    + "data: "
                    + json.dumps(ide.event_snapshot(), ensure_ascii=False)
                    + "\n\n"
                ).encode("utf-8")
                self._send(200, body, "text/event-stream")
            case GetRoute.APPROVALS:
                self._handle_approvals_get()
            case (
                GetRoute.BROWSER
                | GetRoute.FAVICON
                | GetRoute.LEGACY_UI
                | GetRoute.WORKSPACE
                | GetRoute.BOOTSTRAP
                | GetRoute.ROOT
                | GetRoute.STATUS
                | GetRoute.CONTRACT
                | GetRoute.JOBS
                | GetRoute.RUNS
                | GetRoute.SKILLS
                | GetRoute.AGENT_CARD
                | GetRoute.NOT_FOUND
            ):
                raise AssertionError("non-protected GET route dispatched as protected")
            case _ as unreachable:
                assert_never(unreachable)

    def _handle_checkpoint_get(self) -> None:
        from .. import ide

        workspace = ide.workspace_from_path(self.path)
        route = urlsplit(self.path).path
        manager = _checkpoint_manager()
        diff_match = re.fullmatch(r"/api/checkpoints/([0-9a-fA-F]{4,40})/diff", route)
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

    def _handle_approvals_get(self) -> None:
        from .. import risk as risk_mod
        from .. import uistate

        items = risk_mod.sort_by_risk(approvals.reviewable_pending())
        for item in items:
            item["risk"] = risk_mod.risk_for(item.get("category", ""))
            item["ui_state"] = uistate.from_approval(item).state
        self._json(items)

    def _handle_public_get(self, get_route: GetRoute) -> None:
        match get_route:
            case GetRoute.ROOT:
                html = (_STATIC / "index.html").read_text(encoding="utf-8")
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            case GetRoute.STATUS:
                self._json(_status_payload())
            case GetRoute.CONTRACT:
                try:
                    payload = workspace_contract()
                except (OSError, RuntimeError, TypeError, ValueError):
                    self._json({"error": "contract unavailable"}, code=500)
                    return
                self._json(payload)
            case GetRoute.JOBS:
                from .. import uistate

                jobs = cron.load_jobs()
                for job in jobs:
                    job["ui_state"] = uistate.from_cron(
                        enabled=bool(job.get("enabled", True)),
                    ).state
                self._json({"status": store.read_status(), "jobs": jobs})
            case GetRoute.RUNS:
                from .. import uistate

                runs = store.list_runs(limit=20)
                for run in runs:
                    run["ui_state"] = uistate.from_recent_run(run).state
                self._json(runs)
            case GetRoute.SKILLS:
                cfg = config.load_config()
                try:
                    manager = build_manager(cfg)
                    self._json(
                        [
                            {
                                "name": skill.name,
                                "description": skill.description,
                                "source": skill.source,
                            }
                            for skill in sorted(
                                manager.skills.values(), key=lambda value: value.name
                            )
                        ]
                    )
                except (OSError, RuntimeError, TypeError, ValueError):
                    self._json({"error": "skills unavailable"}, code=500)
            case GetRoute.AGENT_CARD:
                from .. import a2a

                cfg = config.load_config()
                if not a2a.enabled(cfg):
                    self._send(404, b"not found", "text/plain")
                    return
                external = _listener_external_origin(self.server)
                host = self.headers.get("Host") or "127.0.0.1"
                base_url = (
                    external.origin if external is not None else f"http://{host}"
                )
                self._json(a2a.agent_card(base_url, cfg))
            case GetRoute.NOT_FOUND:
                self._send(404, b"not found", "text/plain")
            case (
                GetRoute.BROWSER
                | GetRoute.FAVICON
                | GetRoute.LEGACY_UI
                | GetRoute.WORKSPACE
                | GetRoute.BOOTSTRAP
                | GetRoute.APPROVAL_DIFF
                | GetRoute.CONFIG
                | GetRoute.AGENT_RUNS
                | GetRoute.AGENT_RUN
                | GetRoute.ACTION_RECEIPT
                | GetRoute.CHECKPOINTS
                | GetRoute.EVENTS
                | GetRoute.APPROVALS
            ):
                raise AssertionError("non-public GET route dispatched as public")
            case _ as unreachable:
                assert_never(unreachable)

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
            self._json(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "parse error"},
                },
                code=400,
            )
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
        route = match_post(self.path)
        post_route = route.route
        match post_route:
            case PostRoute.BROWSER:
                self._handle_browser_post()
                return
            case (
                PostRoute.WORKSPACE
                | PostRoute.A2A
                | PostRoute.CONTEXT
                | PostRoute.RUN_CONTROL
                | PostRoute.CHECKPOINT
                | PostRoute.INVALID_CHECKPOINT
                | PostRoute.APPROVALS
                | PostRoute.NOT_FOUND
            ):
                pass
            case _ as unreachable:
                assert_never(unreachable)
        if not self._admit_post():
            return
        match post_route:
            case PostRoute.WORKSPACE:
                _ = self._workspace_post()
            case PostRoute.A2A:
                self._handle_a2a()
            case PostRoute.INVALID_CHECKPOINT:
                self._drain_body()
                self._json({"error": "invalid checkpoint id"}, code=400)
            case PostRoute.NOT_FOUND:
                self._drain_body()
                self._send(404, b"not found", "text/plain")
            case (
                PostRoute.CONTEXT
                | PostRoute.RUN_CONTROL
                | PostRoute.CHECKPOINT
                | PostRoute.APPROVALS
            ):
                payload = self._read_json_object()
                if payload is not None:
                    self._dispatch_post(route, post_route, payload)
            case PostRoute.BROWSER:
                raise AssertionError("browser POST reached shared admission")
            case _ as unreachable:
                assert_never(unreachable)

    def _handle_browser_post(self) -> None:
        if not self._host_ok():
            self._send(403, b"forbidden host", "text/plain")
            return
        if not self._capability_ok():
            self._json({"error": "missing or invalid token"}, code=403)
            return
        denial = self._browser_denial("POST")
        if denial is not None:
            self._send_browser_denial(denial)
            return
        body, body_status = self._read_body()
        if body is None:
            self._json({"error": {"code": "invalid_request"}}, code=body_status)
            return
        self._browser_response(
            post_browser(
                self.path,
                body,
                actor_id=self._browser_actor_id(),
                workspace=_browser_workspace(self.server),
            )
        )

    def _admit_post(self) -> bool:
        if not self._host_ok():
            self._drain_body()
            self._send(403, b"forbidden host", "text/plain")
            return False
        if not self._capability_ok():
            self._drain_body()
            self._json({"error": "missing or invalid token"}, code=403)
            return False
        if not self._cookie_origin_ok(write=True):
            self._drain_body()
            self._json({"error": "cross-origin capability request"}, code=403)
            return False
        if (
            self._cookie_capability_ok()
            and not self._header_capability_ok()
            and self.headers.get_content_type() != "application/json"
        ):
            self._drain_body()
            self._json({"error": "application/json required"}, code=415)
            return False
        return True

    def _read_json_object(self) -> dict[str, JSONValue] | None:
        body, body_status = self._read_body()
        if body_status != 200:
            message = {
                408: "request body timeout",
                413: "payload too large",
            }.get(body_status, "bad content length")
            self._json({"error": message}, code=body_status)
            return None
        try:
            return parse_object(body or b"{}")
        except RequestPayloadError as exc:
            self._json({"error": str(exc)}, code=400)
            return None

    def _dispatch_post(
        self,
        route: RouteMatch[PostRoute],
        post_route: PostRoute,
        payload: dict[str, JSONValue],
    ) -> None:
        match post_route:
            case PostRoute.CONTEXT:
                from .. import ide

                if not ide.save_context(payload):
                    self._json({"error": "invalid editor context"}, code=400)
                    return
                self._json({"ok": True})
            case PostRoute.RUN_CONTROL:
                from . import approval_console

                code, result = approval_console.control_run(
                    route.identifier,
                    payload.get("action"),
                    payload.get("text"),
                )
                self._json(result, code=code)
            case PostRoute.CHECKPOINT:
                self._handle_checkpoint_post(route, payload)
            case PostRoute.APPROVALS:
                self._handle_approval_post(payload)
            case (
                PostRoute.BROWSER
                | PostRoute.WORKSPACE
                | PostRoute.A2A
                | PostRoute.INVALID_CHECKPOINT
                | PostRoute.NOT_FOUND
            ):
                raise AssertionError("bodyless POST route dispatched with payload")
            case _ as unreachable:
                assert_never(unreachable)

    def _handle_checkpoint_post(
        self,
        route: RouteMatch[PostRoute],
        payload: dict[str, JSONValue],
    ) -> None:
        workspace = (
            Path(str(payload.get("workspace") or Path.cwd())).expanduser().resolve()
        )
        if route.action == "restore":
            self._handle_checkpoint_restore(route.identifier, workspace, payload)
            return
        command = string_list(payload.get("command"))
        if not command or not all(command):
            self._json({"error": "command must be a non-empty string array"}, code=400)
            return
        from ..sandbox import load_repo_sandbox

        spec = load_repo_sandbox(workspace)
        try:
            result = _checkpoint_manager().fork(
                workspace, route.identifier, command, policy=spec.policy
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            self._json({"error": "checkpoint fork failed"}, code=409)
            return
        self._json(
            {
                "ok": True,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            code=200 if result.returncode == 0 else 409,
        )

    def _handle_checkpoint_restore(
        self,
        checkpoint: str,
        workspace: Path,
        payload: dict[str, JSONValue],
    ) -> None:
        from ..checkpoints import RestoreMode

        try:
            mode = RestoreMode(str(payload.get("mode") or ""))
        except ValueError:
            self._json({"error": "mode must be files, task, or both"}, code=400)
            return
        session_id = str(payload.get("session_id") or "")
        if mode is not RestoreMode.FILES and not session_id:
            self._json({"error": "session_id is required"}, code=400)
            return
        target = f" for session {session_id}" if session_id else ""
        restore_payload = {
            "workspace": str(workspace),
            "checkpoint": checkpoint,
            "mode": mode.value,
        }
        if session_id:
            restore_payload["session_id"] = session_id
        proposal = approvals.propose(
            category="checkpoint_restore",
            title=f"Restore checkpoint {checkpoint[:7]}",
            description=(
                f"Restore {mode.value} for {workspace}{target}. "
                "This destructive action is undo-checkpointed before execution."
            ),
            payload=restore_payload,
            cfg=config.load_config(),
            origin="web:checkpoints",
        )
        self._json(
            {
                "ok": True,
                "approval_required": True,
                "approval_id": proposal["id"],
                "mode": mode.value,
            },
            code=202,
        )

    def _handle_approval_post(self, payload: dict[str, JSONValue]) -> None:
        approval_id = payload.get("id")
        action = payload.get("action")
        if not approval_id or action not in ("answer", "approve", "reject"):
            self._json({"error": "need id and action answer|approve|reject"}, code=400)
            return
        if (
            not isinstance(approval_id, str)
            or _APPROVAL_ID_RE.fullmatch(approval_id) is None
        ):
            self._json({"error": "invalid approval id"}, code=400)
            return
        if action == "answer":
            self._handle_approval_answer(approval_id, payload)
            return
        result = (
            approvals.approve(
                approval_id,
                approved_by=self._approval_actor_id(),
                approved_via="web:dashboard",
            )
            if action == "approve"
            else approvals.reject(
                approval_id,
                rejected_by=self._approval_actor_id(),
                rejected_via="web:dashboard",
            )
        )
        self._json(result)

    def _handle_approval_answer(
        self,
        approval_id: str,
        payload: dict[str, JSONValue],
    ) -> None:
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            self._json({"error": "answers must be an object"}, code=400)
            return
        input_schema_version = payload.get("input_schema_version")
        result = approvals.answer(
            approval_id,
            answers=answers,
            source="web:dashboard",
            clarification=str(payload.get("clarification") or ""),
            navigation=string_list(payload.get("navigation")),
            capability="dashboard.approvals.answer.v1",
            resume_token=str(payload.get("resume_token") or ""),
            question_digest=str(payload.get("question_digest") or ""),
            input_schema_version=(
                input_schema_version
                if isinstance(input_schema_version, int)
                and not isinstance(input_schema_version, bool)
                else None
            ),
            previous_state_digest=str(payload.get("previous_state_digest") or ""),
        )
        self._json(result, code=200 if result.get("ok") else 409)

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
        self._browser_response(
            delete_browser(
                self.path,
                actor_id=self._browser_actor_id(),
                workspace=_browser_workspace(self.server),
            )
        )

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
    from ..approval_execution_recovery import recover_all
    from ..moirai import continuation

    recover_all()
    continuation.recover()
    cfg = config.load_config()
    port = port or int(cfg.get("web_port", 8787))
    remote = bool(cfg.get("web_remote_access", False))
    try:
        external = parse_web_external_url(
            cfg.get("web_external_url", "")
        )
    except ValueError as exc:
        print(f"WebUI refused before bind: {exc}", file=sys.stderr)
        return 2
    if remote and (external is None or not external.secure):
        print(
            "remote WebUI refused before bind: web_external_url must "
            "be an https:// origin",
            file=sys.stderr,
        )
        return 2
    if external is not None and not remote:
        print(
            "WebUI refused before bind: web_external_url requires "
            "web_remote_access=true",
            file=sys.stderr,
        )
        return 2
    url_host = socket.getfqdn() if remote else "127.0.0.1"
    bind_host = "" if remote else url_host
    httpd = HTTPServer((bind_host, port), Handler)
    _set_listener_external_origin(httpd, external)
    _set_listener_remote_access(httpd, remote)
    actual_port = int(httpd.server_address[1])
    bootstrap_nonce = _bootstrap_nonce(httpd)
    os.environ["BIRKIN_BROWSER_CONTROL_ADDRESSES"] = (
        f"127.0.0.1:{actual_port},localhost:{actual_port}"
    )
    session_path = config.birkin_home() / "web_session.json"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    store._write_json(
        session_path,
        {
            "port": actual_port,
            "token": _CAPABILITY_TOKEN,
            "bootstrap_nonce": bootstrap_nonce,
        },
    )
    url = (
        external.origin
        if external is not None
        else f"http://127.0.0.1:{actual_port}"
    )
    bootstrap_url = f"{url}/_bootstrap/{bootstrap_nonce}"
    print(f"birkin workspace running at {bootstrap_url}  (Ctrl-C to stop)")
    if open_browser and not remote:
        try:
            _ = webbrowser.open(bootstrap_url)
        except (OSError, webbrowser.Error):
            print("could not open the dashboard URL automatically")
    elif open_browser:
        print(
            "automatic browser opening is disabled for remote access; "
            "open the printed one-time URL on the remote device"
        )
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
        _close_workspace_runtime()
        try:
            _ = close_browser_service(workspace=_browser_workspace(httpd))
        finally:
            try:
                browser_workspace_registry().close_all()
            except BrowserAsideError:
                pass
            finally:
                try:
                    session_path.unlink(missing_ok=True)
                finally:
                    httpd.server_close()
    return 0
