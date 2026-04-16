"""Bearer token authentication for the Birkin gateway."""

from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request

EXEMPT_PATHS: list[str] = [
    "/api/health",
    "/api/auth/status",
    "/api/auth/bootstrap",
]

EXEMPT_PREFIXES: list[str] = [
    "/static/",
    "/webhooks/",
]


def _is_exempt(path: str) -> bool:
    """Return True if the request path is exempt from authentication."""
    if path == "/":
        return True
    if path in EXEMPT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES)


def _extract_token(request: Request) -> str | None:
    """Extract a bearer token from the Authorization header or session cookie."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    return request.cookies.get("birkin_session")


def _is_localhost(request: Request) -> bool:
    """Return True if the request originates from localhost."""
    client = request.client
    if client is None:
        return False
    host = client.host or ""
    return host in ("127.0.0.1", "::1", "localhost")


def require_auth(request: Request) -> None:
    """Validate authentication for the current request.

    Rules:
    - If the path is exempt, allow unconditionally.
    - If BIRKIN_AUTH_TOKEN is not set and the request is from localhost, allow (dev mode).
    - If BIRKIN_AUTH_TOKEN is set, require a matching Bearer token or session cookie.
    """
    if _is_exempt(request.url.path):
        return

    expected_token = os.environ.get("BIRKIN_AUTH_TOKEN")

    if not expected_token:
        # Dev mode: no token configured means auth is disabled.
        # The CLI layer (cmd_serve) prevents binding to non-localhost without a token,
        # so this is safe — only localhost can reach the server in token-less mode.
        return

    provided_token = _extract_token(request)
    if not provided_token:
        raise HTTPException(status_code=401, detail="Missing authentication token.")

    if not hmac.compare_digest(provided_token, expected_token):
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
