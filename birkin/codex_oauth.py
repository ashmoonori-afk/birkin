"""OpenAI Codex OAuth — birkin's own ChatGPT session, independent of the CLI.

birkin talks to the ChatGPT Codex backend in-process using an OAuth access
token, the same way :mod:`birkin.oauth` does for Anthropic. Inference is billed
against the user's ChatGPT subscription, so no ``OPENAI_API_KEY`` is required.

**Why a separate token store.** The obvious shortcut — read (or copy)
``~/.codex/auth.json`` and refresh that — silently destroys the user's codex CLI
login. OpenAI rotates the refresh token on every grant, so the moment birkin
refreshes a token it borrowed, the copy the CLI still holds is dead. birkin
therefore keeps its **own** credential at ``$BIRKIN_HOME/codex-auth.json`` with
its own refresh chain and never writes to ``~/.codex/``.

Requests need more than a bearer token: the Cloudflare layer in front of
``chatgpt.com/backend-api/codex`` whitelists a small set of first-party
originators, so :func:`auth_headers` pins ``originator: codex_cli_rs`` and a
matching user-agent, and carries the account id the backend expects.

Pure standard library: ``urllib`` only, no third-party packages.

Ported (and trimmed) from hermes-agent ``hermes_cli/auth.py`` and
``agent/auxiliary_client.py`` (MIT).
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

DEFAULT_BASE_URL = "https://chatgpt.com/backend-api/codex"

_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_ISSUER = "https://auth.openai.com"
_TOKEN_URL = f"{_ISSUER}/oauth/token"
_DEVICE_CODE_URL = f"{_ISSUER}/api/accounts/deviceauth/usercode"
_DEVICE_TOKEN_URL = f"{_ISSUER}/api/accounts/deviceauth/token"
_DEVICE_REDIRECT_URI = f"{_ISSUER}/deviceauth/callback"
_DEVICE_VERIFY_URL = f"{_ISSUER}/codex/device"

# Refresh this long before the JWT's own expiry, so a request never races the
# clock. Matches the codex CLI's own skew.
_REFRESH_SKEW_SECONDS = 120

# Cloudflare fronts both auth.openai.com and the Codex backend and whitelists a
# small set of first-party originators. It rejects urllib's default user-agent
# with a 530 ("A 1xxx error occured") before any OpenAI handler sees the
# request, so every call here — login included, not just inference — has to
# announce itself as the codex CLI.
_IDENTITY_HEADERS = {
    "User-Agent": "codex_cli_rs/0.0.0 (birkin)",
    "originator": "codex_cli_rs",
}

# Serializes refresh so concurrent callers don't both spend the single-use
# refresh_token (the loser would 400 and look "logged out").
_token_lock = threading.Lock()


class CodexAuthError(RuntimeError):
    """Codex OAuth failed in a way the user has to act on."""


# --- token store ----------------------------------------------------------

def store_path() -> Path:
    """birkin's own Codex credential — never ``~/.codex/auth.json``."""
    from .config import birkin_home
    return birkin_home() / "codex-auth.json"


def _read_store() -> Optional[dict[str, Any]]:
    path = store_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    tokens = data.get("tokens")
    if not isinstance(tokens, dict) or not tokens.get("access_token"):
        return None
    return data


def _write_store(tokens: dict[str, str]) -> None:
    """Persist tokens atomically, 0600 where the OS honours it.

    The rename is what matters: a crash mid-write leaves the old credential,
    never a truncated one, and no readable ``.tmp`` behind. On Windows
    ``chmod`` only toggles the read-only bit, so the mode is a no-op there and
    the file rests on the profile directory's ACL — same as ``~/.codex``.
    """
    path = store_path()
    payload = {
        "tokens": tokens,
        "auth_mode": "chatgpt",
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except OSError:
        # Never leave a half-written .tmp holding a token behind.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def is_logged_in() -> bool:
    """True when birkin holds a Codex credential. No network, no refresh."""
    return _read_store() is not None


def logout() -> bool:
    """Forget birkin's Codex credential. Returns True if one was removed."""
    try:
        store_path().unlink()
        return True
    except OSError:
        return False


# --- JWT helpers ----------------------------------------------------------

def jwt_claims(token: str) -> dict[str, Any]:
    """Decode a JWT payload without verifying — we only read our own token.

    Returns ``{}`` for anything unparseable; callers must treat that as
    "unknown", never as "valid".
    """
    if not isinstance(token, str):
        return {}
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}
    return claims if isinstance(claims, dict) else {}


def _is_expiring(access_token: str, skew_seconds: int) -> bool:
    """True when the token is expired, near expiry, or unreadable.

    Unreadable fails toward refreshing: a needless refresh costs one request,
    while using a dead token costs the whole call.
    """
    exp = jwt_claims(access_token).get("exp")
    if not isinstance(exp, (int, float)):
        return True
    return time.time() >= (float(exp) - skew_seconds)


def account_id(access_token: str, tokens: Optional[dict] = None) -> str:
    """ChatGPT account id — from the stored token, else the JWT claim."""
    if tokens:
        stored = tokens.get("account_id")
        if isinstance(stored, str) and stored.strip():
            return stored.strip()
    auth = jwt_claims(access_token).get("https://api.openai.com/auth")
    if isinstance(auth, dict):
        acct = auth.get("chatgpt_account_id")
        if isinstance(acct, str) and acct.strip():
            return acct.strip()
    return ""


# --- HTTP -----------------------------------------------------------------

def _post(url: str, *, form: Optional[dict] = None,
          payload: Optional[dict] = None,
          timeout: int = 20) -> tuple[int, dict[str, Any]]:
    """POST form-encoded or JSON; return (status, decoded-json-or-{})."""
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        ctype = "application/x-www-form-urlencoded"
    else:
        body = json.dumps(payload or {}).encode()
        ctype = "application/json"
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": ctype,
        "Accept": "application/json",
        **_IDENTITY_HEADERS,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        status = exc.code
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise CodexAuthError(f"could not reach {url}: {exc}") from exc
    try:
        decoded = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        decoded = {}
    return status, (decoded if isinstance(decoded, dict) else {})


def refresh(refresh_token: str) -> dict[str, str]:
    """Exchange a refresh_token for a fresh access token.

    Raises :class:`CodexAuthError` — a failed refresh means the user must log
    in again, and silently returning None would surface later as a confusing
    401 from the inference call.
    """
    if not (isinstance(refresh_token, str) and refresh_token.strip()):
        raise CodexAuthError(
            "no refresh_token stored — run `birkin auth codex login`")
    status, data = _post(_TOKEN_URL, form={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": _CLIENT_ID,
    })
    if status != 200:
        raise CodexAuthError(
            f"codex token refresh failed (HTTP {status}) — "
            f"{_describe_error(data)} run `birkin auth codex login`")
    access = data.get("access_token")
    if not access:
        raise CodexAuthError(
            "codex token refresh returned no access_token — "
            "run `birkin auth codex login`")
    # OpenAI rotates the refresh token; keep the new one or we burn ourselves.
    return {
        "access_token": access,
        "refresh_token": data.get("refresh_token") or refresh_token,
        "id_token": data.get("id_token", ""),
    }


def _describe_error(data: dict[str, Any]) -> str:
    err = data.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("code") or err.get("type")
        if isinstance(msg, str) and msg.strip():
            return msg.strip() + "."
    if isinstance(err, str) and err.strip():
        desc = data.get("error_description")
        if isinstance(desc, str) and desc.strip():
            return f"{err.strip()}: {desc.strip()}."
        return err.strip() + "."
    return ""


# --- login ----------------------------------------------------------------

def device_login(emit: Callable[[str], None] = print,
                 poll_seconds: Optional[int] = None,
                 max_wait_seconds: int = 15 * 60,
                 sleep: Callable[[float], None] = time.sleep) -> dict[str, str]:
    """OAuth device-code login. Prints a code the user enters in a browser.

    Returns the token dict and persists it. This mints birkin its **own**
    refresh chain, which is what keeps the codex CLI's login intact.
    """
    status, device = _post(_DEVICE_CODE_URL, payload={"client_id": _CLIENT_ID})
    if status != 200:
        raise CodexAuthError(
            f"could not start device login (HTTP {status}). "
            f"{_describe_error(device)}".strip())
    user_code = str(device.get("user_code") or "")
    device_auth_id = str(device.get("device_auth_id") or "")
    if not user_code or not device_auth_id:
        raise CodexAuthError("device login response was missing fields")
    interval = poll_seconds if poll_seconds is not None else max(
        3, int(device.get("interval") or 5))

    emit("")
    emit("  1. 브라우저에서 열기:")
    emit(f"     {_DEVICE_VERIFY_URL}")
    emit("")
    emit("  2. 이 코드 입력:")
    emit(f"     {user_code}")
    emit("")
    emit("로그인 대기 중… (Ctrl+C 로 취소)")

    deadline = time.monotonic() + max_wait_seconds
    granted: dict[str, Any] = {}
    while time.monotonic() < deadline:
        sleep(interval)
        status, body = _post(_DEVICE_TOKEN_URL, payload={
            "device_auth_id": device_auth_id, "user_code": user_code})
        if status == 200:
            granted = body
            break
        if status in (403, 404):
            continue  # not approved yet
        raise CodexAuthError(
            f"device login polling failed (HTTP {status}). "
            f"{_describe_error(body)}".strip())
    if not granted:
        raise CodexAuthError("device login timed out")

    code = str(granted.get("authorization_code") or "")
    verifier = str(granted.get("code_verifier") or "")
    if not code or not verifier:
        raise CodexAuthError("device login did not return an authorization code")

    status, data = _post(_TOKEN_URL, form={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _DEVICE_REDIRECT_URI,
        "client_id": _CLIENT_ID,
        "code_verifier": verifier,
    })
    if status != 200 or not data.get("access_token"):
        raise CodexAuthError(
            f"codex token exchange failed (HTTP {status}). "
            f"{_describe_error(data)}".strip())

    access = str(data["access_token"])
    tokens = {
        "access_token": access,
        "refresh_token": str(data.get("refresh_token") or ""),
        "id_token": str(data.get("id_token") or ""),
        "account_id": account_id(access),
    }
    _write_store(tokens)
    return tokens


def import_cli_tokens() -> dict[str, str]:
    """Adopt the codex CLI's credential from ``~/.codex/auth.json`` (read-only).

    **This burns the CLI login.** Refresh-token rotation means birkin's first
    refresh invalidates the copy the CLI still holds, so this is opt-in only;
    :func:`device_login` is the path that leaves both sessions working.
    """
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    root = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    path = root / "auth.json"
    if not path.is_file():
        raise CodexAuthError(f"no codex CLI credential at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CodexAuthError(f"could not read {path}: {exc}") from exc
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        raise CodexAuthError(f"{path} has no tokens — run `codex login` first")
    access = str(tokens.get("access_token") or "")
    refresh_token = str(tokens.get("refresh_token") or "")
    if not access or not refresh_token:
        raise CodexAuthError(f"{path} is missing access/refresh tokens")
    adopted = {
        "access_token": access,
        "refresh_token": refresh_token,
        "id_token": str(tokens.get("id_token") or ""),
        "account_id": str(tokens.get("account_id") or "") or account_id(access),
    }
    _write_store(adopted)
    return adopted


# --- runtime --------------------------------------------------------------

def _refresh_locked(tokens: dict[str, Any]) -> str:
    """Exchange the refresh token while holding a cross-process lock.

    ``_token_lock`` is per-interpreter, but birkin's CLI, gateway daemon and
    WebUI are separate processes sharing this store. OpenAI rotates the refresh
    token on every grant, so without a cross-process lock the loser of a race
    spends a token the winner already invalidated: it 400s and looks logged
    out. Re-reading after winning the lock is what makes the loser adopt the
    winner's fresh token instead.
    """
    from . import store
    try:
        with store.file_lock(store_path()):
            current = _read_store()
            fresh = dict(current["tokens"]) if current else dict(tokens)
            access = str(fresh.get("access_token") or "")
            if access and not _is_expiring(access, _REFRESH_SKEW_SECONDS):
                return access                      # another process refreshed
            fresh.update(refresh(str(fresh.get("refresh_token") or "")))
            if not fresh.get("account_id"):
                fresh["account_id"] = account_id(fresh["access_token"])
            _write_store(fresh)
            return str(fresh["access_token"])
    except store.FileLockTimeout:
        current = _read_store()
        access = str(((current or {}).get("tokens") or {}).get("access_token") or "")
        if access and not _is_expiring(access, _REFRESH_SKEW_SECONDS):
            return access
        raise CodexAuthError(
            "another birkin process is refreshing the Codex token — retry")


def resolve_token(*, refresh_if_expiring: bool = True) -> Optional[str]:
    """Return a usable access token, refreshing and persisting when stale.

    ``None`` means "not logged in" — callers fall back to the codex CLI. A
    *failed* refresh raises instead, because that is a real problem the user
    needs told about rather than a silent downgrade.
    """
    with _token_lock:
        data = _read_store()
        if not data:
            return None
        tokens = dict(data["tokens"])
        access = str(tokens.get("access_token") or "")
        if refresh_if_expiring and _is_expiring(access, _REFRESH_SKEW_SECONDS):
            access = _refresh_locked(tokens)
        return access or None


def base_url() -> str:
    return (os.environ.get("BIRKIN_CODEX_BASE_URL", "").strip().rstrip("/")
            or DEFAULT_BASE_URL)


def auth_headers(token: str) -> dict[str, str]:
    """Bearer + the first-party identity the Codex edge requires.

    Without ``originator``/user-agent, Cloudflare answers a 403 challenge
    regardless of whether the token is good.
    """
    headers = {"Authorization": f"Bearer {token}", **_IDENTITY_HEADERS}
    data = _read_store() or {}
    acct = account_id(token, data.get("tokens") if data else None)
    if acct:
        headers["ChatGPT-Account-ID"] = acct
    return headers


def status() -> dict[str, Any]:
    """Non-secret summary for ``birkin auth codex status``."""
    data = _read_store()
    if not data:
        return {"logged_in": False}
    tokens = data.get("tokens") or {}
    access = str(tokens.get("access_token") or "")
    exp = jwt_claims(access).get("exp")
    return {
        "logged_in": True,
        "store": str(store_path()),
        "account_id": account_id(access, tokens),
        "last_refresh": data.get("last_refresh", ""),
        "expires_in_seconds": (int(float(exp) - time.time())
                               if isinstance(exp, (int, float)) else None),
        "base_url": base_url(),
    }
