"""Claude credential diagnosis.

`read_credentials()` returns None for "no file" and for "file present but the
token strings are empty" alike. Claude Code leaves the metadata behind when the
secret lives elsewhere, so the second case reads as "expired" when nothing has
expired — which is exactly the wrong thing to tell someone.
"""

from __future__ import annotations

import json

import pytest

from birkin import oauth


@pytest.fixture()
def creds(tmp_path, monkeypatch):
    path = tmp_path / ".credentials.json"
    monkeypatch.setattr(oauth, "_credentials_path", lambda: path)
    monkeypatch.setattr(oauth, "_read_keychain", lambda: None)
    for name in ("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
                 "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return path


def test_missing_file(creds):
    info = oauth.diagnose()
    assert info["state"] == "missing"
    assert info["token"] is False
    assert "claude /login" in oauth.explain(info)


def test_emptied_tokens_are_not_reported_as_expired(creds):
    """The real shape on this machine: metadata kept, secrets blanked."""
    creds.write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "", "refreshToken": "", "expiresAt": 0,
        "refreshTokenExpiresAt": 1786431950102,
        "scopes": ["user:inference"], "subscriptionType": "max"}}),
        encoding="utf-8")

    info = oauth.diagnose()
    assert info["state"] == "emptied"
    assert info["access_token_len"] == 0
    assert info["refresh_token_len"] == 0
    assert info["subscription"] == "max"
    assert info["token"] is False
    message = oauth.explain(info)
    assert "EMPTY" in message
    assert "setup-token" in message
    assert "expired" not in message.lower()


def test_no_oauth_block(creds):
    creds.write_text(json.dumps({"mcpOAuth": {}}), encoding="utf-8")
    info = oauth.diagnose()
    assert info["state"] == "no_oauth_block"
    assert info["has_oauth_block"] is False


def test_unreadable_file(creds):
    creds.write_text("{not json", encoding="utf-8")
    info = oauth.diagnose()
    assert info["state"] == "unreadable"
    assert "detail" in info


def test_a_working_token_reports_ok(creds, monkeypatch):
    creds.write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "sk-ant-oat-x", "refreshToken": "r1",
        "expiresAt": 4102444800000, "scopes": ["user:inference"]}}),
        encoding="utf-8")
    info = oauth.diagnose()
    assert info["state"] == "ok"
    assert info["token"] is True
    assert oauth.explain(info) == "logged in"


def test_env_fallback_is_reported(creds, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-env")
    info = oauth.diagnose()
    assert "CLAUDE_CODE_OAUTH_TOKEN" in info["env"]
    assert info["state"] == "ok"
    assert info["token"] is True


def test_diagnose_never_returns_the_secret(creds):
    creds.write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "sk-ant-oat-SECRET", "refreshToken": "REFRESH-SECRET",
        "expiresAt": 4102444800000}}), encoding="utf-8")
    blob = json.dumps(oauth.diagnose())
    assert "SECRET" not in blob
