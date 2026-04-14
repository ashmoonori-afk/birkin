"""
Birkin — Chat API backend.

Lightweight FastAPI server providing chat endpoints for the WebUI.
Stub implementations return mock responses until BRA-51 (core agent runtime)
is integrated.

Usage:
    uvicorn web.api:app --port 9119 --reload
"""

import hashlib
import secrets
import time
import uuid
from pathlib import Path
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException, Depends, Header
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError:
    raise SystemExit(
        "Web API requires fastapi and uvicorn.\n"
        "Install: pip install fastapi uvicorn"
    )

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Birkin", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory stores (replaced by real DB/runtime in BRA-51 integration)
# ---------------------------------------------------------------------------

# Default user for the stub (password: "birkin")
_USERS = {
    "admin": {
        "id": "usr_default",
        "username": "admin",
        "password_hash": hashlib.sha256(b"birkin").hexdigest(),
    }
}

# Active tokens → user id
_TOKENS: dict[str, str] = {}

# Sessions: id → session dict
_SESSIONS: dict[str, dict] = {}

# Messages: session_id → list of message dicts
_MESSAGES: dict[str, list[dict]] = {}

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _verify_token(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.removeprefix("Bearer ")
    user_id = _TOKENS.get(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = next((u for u in _USERS.values() if u["id"] == user_id), None)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return {"id": user["id"], "username": user["username"]}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class SendMessageRequest(BaseModel):
    content: str


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


@app.post("/api/auth/login")
def auth_login(req: LoginRequest):
    user = _USERS.get(req.username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if hashlib.sha256(req.password.encode()).hexdigest() != user["password_hash"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = secrets.token_urlsafe(32)
    _TOKENS[token] = user["id"]
    return {
        "token": token,
        "user": {"id": user["id"], "username": user["username"]},
    }


@app.get("/api/auth/me")
def auth_me(user: dict = Depends(_verify_token)):
    return user


# ---------------------------------------------------------------------------
# Chat session endpoints
# ---------------------------------------------------------------------------


@app.get("/api/chat/sessions")
def list_sessions(user: dict = Depends(_verify_token)):
    sessions = sorted(
        _SESSIONS.values(), key=lambda s: s["updated_at"], reverse=True
    )
    return {"sessions": sessions}


@app.post("/api/chat/sessions")
def create_session(user: dict = Depends(_verify_token)):
    session_id = str(uuid.uuid4())
    now = time.time()
    session = {
        "id": session_id,
        "title": None,
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
        "preview": None,
    }
    _SESSIONS[session_id] = session
    _MESSAGES[session_id] = []
    return session


@app.get("/api/chat/sessions/{session_id}")
def get_session(session_id: str, user: dict = Depends(_verify_token)):
    session = _SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = _MESSAGES.get(session_id, [])
    return {"session": session, "messages": messages}


@app.delete("/api/chat/sessions/{session_id}")
def delete_session(session_id: str, user: dict = Depends(_verify_token)):
    _SESSIONS.pop(session_id, None)
    _MESSAGES.pop(session_id, None)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Chat message endpoints
# ---------------------------------------------------------------------------


@app.post("/api/chat/sessions/{session_id}/messages")
def send_message(
    session_id: str,
    req: SendMessageRequest,
    user: dict = Depends(_verify_token),
):
    session = _SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    now = time.time()

    # User message
    user_msg = {
        "id": str(uuid.uuid4()),
        "role": "user",
        "content": req.content,
        "timestamp": now,
    }

    # Stub assistant reply (will be replaced by real agent runtime from BRA-51)
    reply = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "content": _generate_stub_reply(req.content),
        "timestamp": now + 0.5,
    }

    msgs = _MESSAGES.setdefault(session_id, [])
    msgs.append(user_msg)
    msgs.append(reply)

    # Update session metadata
    session["message_count"] = len(msgs)
    session["updated_at"] = now
    session["preview"] = reply["content"][:100]
    if session["title"] is None:
        session["title"] = req.content[:50]

    return {"message": user_msg, "reply": reply}


def _generate_stub_reply(user_content: str) -> str:
    """Stub reply generator — replaced by real agent runtime after BRA-51."""
    content_lower = user_content.lower()
    if "hello" in content_lower or "hi" in content_lower:
        return "Hello! I'm Birkin, your AI assistant. How can I help you today?"
    if "help" in content_lower:
        return (
            "I can help with a variety of tasks including:\n\n"
            "- Answering questions\n"
            "- Writing and editing text\n"
            "- Code assistance\n"
            "- Research and analysis\n\n"
            "What would you like to work on?"
        )
    return (
        "I received your message. The full agent runtime is not yet connected "
        "(pending core runtime integration). Once that's ready, I'll be able "
        "to give you real, intelligent responses.\n\n"
        f'You said: "{user_content}"'
    )


# ---------------------------------------------------------------------------
# Static file serving (production build)
# ---------------------------------------------------------------------------

WEB_DIST = Path(__file__).parent / "src" / ".." / ".." / "birkin_cli" / "web_dist"
_DIST = WEB_DIST.resolve()

if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def serve_spa(path: str):
        file = _DIST / path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(_DIST / "index.html")
