"""Cross-process serialization of OAuth token refresh.

birkin runs the CLI, the gateway daemon and the WebUI as separate processes
against one credential store. ``threading.Lock`` only serializes threads inside
a single interpreter, and both providers mint a new refresh token on every
grant, so two processes refreshing at once make the loser spend a token that is
already dead: it gets a 400, surfaces as "logged out", and ``credpool`` files
that under ``auth`` with a 300s cooldown -- hiding the real cause.

hermes (``~/.hermes/auth.json`` "with cross-process file locking") and OpenClaw
("refresh ... under a file lock") both guard this; birkin's port dropped it.
These tests pin the real ``store.file_lock`` being held across the exchange.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def _lock_path(path: Path) -> Path:
    """Where ``store.file_lock`` puts its lock for ``path``."""
    return path.parent / (path.name + ".lock")


def _claude_credentials(access: str, refresh_token: str, *, expired: bool) -> str:
    delta = -60_000 if expired else 3_600_000
    return json.dumps({"claudeAiOauth": {
        "accessToken": access,
        "refreshToken": refresh_token,
        "expiresAt": int(time.time() * 1000) + delta,
        "scopes": ["user:inference"],
    }})


# -- Anthropic ---------------------------------------------------------------

def test_claude_refresh_runs_under_the_cross_process_lock(tmp_path, monkeypatch):
    from birkin import oauth

    cred = tmp_path / ".credentials.json"
    cred.write_text(_claude_credentials("stale", "R1", expired=True),
                    encoding="utf-8")
    monkeypatch.setattr(oauth, "_credentials_path", lambda: cred)
    monkeypatch.setattr(oauth, "_read_keychain", lambda: None)
    monkeypatch.delenv("ANTHROPIC_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    seen: dict[str, object] = {}

    def fake_refresh(refresh_token: str):
        seen["held"] = _lock_path(cred).exists()
        seen["spent"] = refresh_token
        return {"access_token": "fresh", "refresh_token": "R2",
                "expires_at_ms": int(time.time() * 1000) + 3_600_000}

    monkeypatch.setattr(oauth, "refresh", fake_refresh)

    assert oauth.resolve_token() == "fresh"
    assert seen["spent"] == "R1"
    assert seen["held"] is True, \
        "token exchange ran without holding the cross-process lock"
    assert not _lock_path(cred).exists(), "lock file leaked after refresh"


def test_claude_refresh_reuses_what_another_process_just_wrote(tmp_path,
                                                               monkeypatch):
    """The loser of a refresh race must re-read, not spend a rotated token."""
    from birkin import oauth, store

    cred = tmp_path / ".credentials.json"
    cred.write_text(_claude_credentials("stale", "R1", expired=True),
                    encoding="utf-8")
    monkeypatch.setattr(oauth, "_credentials_path", lambda: cred)
    monkeypatch.setattr(oauth, "_read_keychain", lambda: None)
    monkeypatch.delenv("ANTHROPIC_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    spent: list[str] = []
    monkeypatch.setattr(oauth, "refresh",
                        lambda rt: spent.append(rt) or None)

    class WinnerFinishesFirst(store.file_lock):
        """Another process completes its refresh while we wait for the lock."""

        def __enter__(self):
            held = super().__enter__()
            cred.write_text(_claude_credentials("winner", "R2", expired=False),
                            encoding="utf-8")
            return held

    monkeypatch.setattr(store, "file_lock", WinnerFinishesFirst)

    assert oauth.resolve_token() == "winner"
    assert spent == [], "spent a rotated refresh token instead of re-reading"


# -- OpenAI Codex ------------------------------------------------------------

def test_codex_refresh_runs_under_the_cross_process_lock(tmp_path, monkeypatch):
    from birkin import codex_oauth

    store_file = tmp_path / "codex-auth.json"
    store_file.write_text(json.dumps({
        "tokens": {"access_token": "stale", "refresh_token": "R1",
                   "account_id": "acct-1"},
        "auth_mode": "chatgpt",
    }), encoding="utf-8")
    monkeypatch.setattr(codex_oauth, "store_path", lambda: store_file)

    seen: dict[str, object] = {}

    def fake_refresh(refresh_token: str):
        seen["held"] = _lock_path(store_file).exists()
        seen["spent"] = refresh_token
        return {"access_token": "fresh", "refresh_token": "R2", "id_token": ""}

    monkeypatch.setattr(codex_oauth, "refresh", fake_refresh)

    assert codex_oauth.resolve_token() == "fresh"
    assert seen["spent"] == "R1"
    assert seen["held"] is True, \
        "token exchange ran without holding the cross-process lock"
    assert not _lock_path(store_file).exists(), "lock file leaked after refresh"


# -- consent gate (regression pin) -------------------------------------------

def test_subscription_credentials_need_an_explicit_provider_opt_in(monkeypatch):
    """Reading the Claude subscription credential requires choosing the provider.

    hermes gates external-credential auto-discovery behind an explicit user
    choice. birkin gets the same property structurally -- the default provider
    is the paid API key and only ``claude-oauth`` reaches ``oauth`` -- so this
    pins that property rather than reimplementing the gate.
    """
    from birkin import config, oauth

    assert config.DEFAULT_CONFIG["provider"] == "anthropic"
    assert config.OAUTH_PROVIDERS == {"claude-oauth"}

    discovered: list[int] = []
    monkeypatch.setattr(oauth, "resolve_token",
                        lambda: discovered.append(1) or "subscription-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-paid")

    assert config.get_api_key({"provider": "anthropic"}) == "sk-ant-api03-paid"
    assert discovered == [], \
        "read the Claude subscription credential without an explicit opt-in"

    assert config.get_api_key({"provider": "claude-oauth"}) == "subscription-token"
    assert discovered == [1]
