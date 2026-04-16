"""Authentication endpoints."""

from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/auth/status")
def auth_status(request: Request) -> dict:
    """Return whether authentication is required and whether the caller is authenticated."""
    expected_token = os.environ.get("BIRKIN_AUTH_TOKEN")
    auth_required = bool(expected_token)
    authenticated = False

    if not auth_required:
        authenticated = True
    else:
        from birkin.gateway.auth import _extract_token

        provided = _extract_token(request)
        if provided and hmac.compare_digest(provided, expected_token):
            authenticated = True

    return {"auth_required": auth_required, "authenticated": authenticated}


@router.post("/auth/bootstrap")
def auth_bootstrap(body: dict) -> JSONResponse:
    """Exchange a token for an HttpOnly session cookie."""
    expected_token = os.environ.get("BIRKIN_AUTH_TOKEN")
    if not expected_token:
        return JSONResponse({"ok": True})

    provided = body.get("token", "")
    if not provided or not hmac.compare_digest(provided, expected_token):
        raise HTTPException(status_code=401, detail="Invalid token.")

    response = JSONResponse({"ok": True})
    response.set_cookie(
        key="birkin_session",
        value=expected_token,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response
