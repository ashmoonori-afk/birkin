"""Anthropic OAuth credentials — reuse the ``claude`` CLI login (free, in-process).

birkin authenticates to the Anthropic Messages API in-process using the OAuth
access token that the ``claude`` CLI stores after ``claude /login`` (or
``claude setup-token``). This is the same mechanism hermes-agent uses, and it is
what makes birkin both **free** and **fast**:

* **Free** — inference is billed against the user's Claude subscription, not a
  paid API key. birkin never requires ``ANTHROPIC_API_KEY``.
* **Fast** — there is no per-message ``claude -p`` subprocess, so the global
  Claude Code hooks (the ~18s/message tax) never run. The request is a single
  in-process HTTPS call.

Credentials live in ``~/.claude/.credentials.json`` under ``claudeAiOauth``
(or, on macOS, the "Claude Code-credentials" Keychain entry). Expired access
tokens are refreshed in-process via the OAuth ``refresh_token`` grant and
written back atomically.

Pure standard library: ``urllib`` only, no third-party packages.

Ported (and trimmed) from hermes-agent ``agent/anthropic_adapter.py`` (MIT).
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

# Beta headers REQUIRED for subscription/OAuth auth (what Claude Code sends).
OAUTH_BETAS = ["claude-code-20250219", "oauth-2025-04-20"]

# OAuth requests must carry the Claude Code identity, or Anthropic intermittently
# 500s / rejects them. The system prompt's FIRST text block must be this line.
CLAUDE_CODE_SYSTEM_PREFIX = (
    "You are Claude Code, Anthropic's official CLI for Claude.")

# Anthropic validates the spoofed user-agent version; a too-old version gets a
# 400. Kept reasonably current; ``claude --version`` overrides this when present.
_CLAUDE_CODE_VERSION_FALLBACK = "2.1.74"
_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_TOKEN_ENDPOINTS = (
    "https://platform.claude.com/v1/oauth/token",
    "https://console.anthropic.com/v1/oauth/token",
)

_version_cache: Optional[str] = None
_version_lock = threading.Lock()
_version_probe_started = False
# Serializes token refresh so concurrent callers don't both spend the
# single-use refresh_token (the loser would 400 and look "logged out").
_token_lock = threading.Lock()


def _credentials_path() -> Path:
    return Path.home() / ".claude" / ".credentials.json"


def _probe_version() -> None:
    """Detect the installed ``claude --version`` off the hot path; cache it."""
    global _version_cache
    from .proc import cli_argv
    for cmd in ("claude", "claude-code"):
        try:
            r = subprocess.run(cli_argv([cmd, "--version"]),
                               capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out:
            ver = out.split()[0]
            if ver and ver[0].isdigit():
                _version_cache = ver
                return
    _version_cache = _CLAUDE_CODE_VERSION_FALLBACK


def claude_code_version() -> str:
    """Spoofed Claude Code version for the OAuth user-agent.

    Returns the (kept-current) fallback immediately and detects the real
    installed version in a background thread, so the first request never blocks
    on a ``claude --version`` subprocess. Anthropic only rejects a *too-old*
    version, and the fallback stays recent, so the pre-detection turns are safe.
    """
    if _version_cache is not None:
        return _version_cache
    global _version_probe_started
    with _version_lock:
        if not _version_probe_started:
            _version_probe_started = True
            threading.Thread(target=_probe_version, daemon=True).start()
    return _CLAUDE_CODE_VERSION_FALLBACK


def user_agent() -> str:
    return f"claude-cli/{claude_code_version()} (external, cli)"


def is_oauth_token(key: Optional[str]) -> bool:
    """True if ``key`` is an Anthropic OAuth/subscription token (not a paid key).

    ``sk-ant-api*`` → regular Console API key (x-api-key); everything else with
    an Anthropic OAuth shape (``sk-ant-*``, ``eyJ`` JWT, ``cc-``) → Bearer OAuth.
    """
    if not key:
        return False
    if key.startswith("sk-ant-api"):
        return False
    return key.startswith(("sk-ant-", "eyJ", "cc-"))


def _extract(data: dict[str, Any], source: str) -> Optional[dict[str, Any]]:
    oauth = data.get("claudeAiOauth")
    if isinstance(oauth, dict) and oauth.get("accessToken"):
        return {
            "accessToken": oauth.get("accessToken", ""),
            "refreshToken": oauth.get("refreshToken", ""),
            "expiresAt": oauth.get("expiresAt", 0),
            "scopes": oauth.get("scopes"),
            "source": source,
        }
    return None


def _read_keychain() -> Optional[dict[str, Any]]:
    """macOS only: read the "Claude Code-credentials" Keychain entry."""
    if platform.system() != "Darwin":
        return None
    try:
        r = subprocess.run(
            ["security", "find-generic-password",
             "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    raw = (r.stdout or "").strip()
    if r.returncode != 0 or not raw:
        return None
    try:
        return _extract(json.loads(raw), "macos_keychain")
    except json.JSONDecodeError:
        return None


def read_credentials() -> Optional[dict[str, Any]]:
    """Read Claude Code OAuth credentials (Keychain on macOS, else JSON file)."""
    kc = _read_keychain()
    if kc:
        return kc
    path = _credentials_path()
    if path.exists():
        try:
            return _extract(json.loads(path.read_text(encoding="utf-8")),
                            "credentials_file")
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _token_valid(creds: dict[str, Any]) -> bool:
    exp = creds.get("expiresAt", 0)
    if not exp:
        return bool(creds.get("accessToken"))
    # expiresAt is epoch milliseconds; keep a 60s safety buffer.
    return int(time.time() * 1000) < (int(exp) - 60_000)


def refresh(refresh_token: str) -> Optional[dict[str, Any]]:
    """Exchange a refresh_token for a fresh access token. Returns dict or None."""
    if not refresh_token:
        return None
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": _OAUTH_CLIENT_ID,
    }).encode()
    for endpoint in _TOKEN_ENDPOINTS:
        req = urllib.request.Request(endpoint, data=body, method="POST", headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": user_agent(),
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
        except Exception as exc:
            if os.environ.get("BIRKIN_DEBUG", "").strip():
                import sys
                print(f"[birkin] oauth refresh failed via {endpoint}: "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        access = result.get("access_token")
        if access:
            return {
                "access_token": access,
                "refresh_token": result.get("refresh_token", refresh_token),
                "expires_at_ms": int(time.time() * 1000)
                + int(result.get("expires_in", 3600)) * 1000,
            }
    return None


def _write_credentials(access: str, refresh_token: str, expires_at_ms: int,
                       scopes: Optional[list] = None) -> None:
    """Persist refreshed credentials back to ~/.claude/.credentials.json.

    ``scopes`` (notably ``user:inference``) are preserved so the ``claude`` CLI's
    own auth check keeps recognising the credential.
    """
    path = _credentials_path()
    try:
        existing: dict[str, Any] = {}
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
        oauth: dict[str, Any] = {
            "accessToken": access,
            "refreshToken": refresh_token,
            "expiresAt": expires_at_ms,
        }
        if scopes is not None:
            oauth["scopes"] = scopes
        elif isinstance(existing.get("claudeAiOauth"), dict) \
                and "scopes" in existing["claudeAiOauth"]:
            oauth["scopes"] = existing["claudeAiOauth"]["scopes"]
        existing["claudeAiOauth"] = oauth
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        tmp.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except (OSError, json.JSONDecodeError):
        # Never leave a half-written .tmp containing a token behind.
        try:
            path.with_suffix(".tmp").unlink()
        except OSError:
            pass


def resolve_token() -> Optional[str]:
    """Resolve a usable OAuth access token, refreshing + persisting if expired.

    Priority:
      1. A refreshable credential file (``~/.claude/.credentials.json``) — used
         first so an expired access token can be refreshed rather than failing.
      2. ``ANTHROPIC_TOKEN`` / ``CLAUDE_CODE_OAUTH_TOKEN`` env vars (static).
      3. A non-refreshable but still-valid credential file token.

    Returns the access token, or ``None`` if the user is not logged in.
    """
    with _token_lock:
        creds = read_credentials()
        if creds and creds.get("refreshToken"):
            if _token_valid(creds):
                return creds["accessToken"]
            refreshed = refresh(creds["refreshToken"])
            if refreshed:
                _write_credentials(refreshed["access_token"],
                                   refreshed["refresh_token"],
                                   refreshed["expires_at_ms"], creds.get("scopes"))
                return refreshed["access_token"]
            # refresh failed — fall through to env / valid file token
        env = (os.environ.get("ANTHROPIC_TOKEN", "").strip()
               or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip())
        if env:
            return env
        if creds and _token_valid(creds):
            return creds["accessToken"]
        return None


def auth_headers(token: str) -> dict[str, str]:
    """Auth + Claude Code identity headers for an OAuth Messages API request.

    Caller adds ``content-type`` and ``anthropic-version`` separately.
    """
    return {
        "authorization": f"Bearer {token}",
        "anthropic-beta": ",".join(OAUTH_BETAS),
        "user-agent": user_agent(),
        "x-app": "cli",
    }
