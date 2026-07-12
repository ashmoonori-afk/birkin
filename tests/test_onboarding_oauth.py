"""P1-4: onboarding welcome + first-touch smoke coverage (oauth was untested)."""

from __future__ import annotations


# -- gateway welcome / help --------------------------------------------------

def test_gateway_welcome_is_friendly_and_grouped():
    from birkin.gateway.core import gateway_help_text, match_command
    txt = gateway_help_text()
    assert "birkin" in txt and "예:" in txt          # intro + example
    assert "💬 명령" in txt and "🔧 관리자용" in txt   # chat vs admin groups
    assert "/new" in txt and "/update" in txt
    # Telegram sends /start on first open; it maps to the same welcome
    assert match_command("/start")[0] == "help"


# -- oauth token classification (was 0 tests) --------------------------------

def test_is_oauth_token_distinguishes_api_key_from_subscription():
    from birkin import oauth
    assert oauth.is_oauth_token("sk-ant-api03-xxxx") is False   # paid API key
    assert oauth.is_oauth_token("sk-ant-oat01-xxxx") is True    # OAuth token
    assert oauth.is_oauth_token("eyJhbGciOi...") is True        # JWT
    assert oauth.is_oauth_token("cc-xxxx") is True
    assert oauth.is_oauth_token("") is False
    assert oauth.is_oauth_token(None) is False


def test_oauth_extract_pulls_credentials():
    from birkin import oauth
    creds = oauth._extract(
        {"claudeAiOauth": {"accessToken": "tok", "refreshToken": "r",
                           "expiresAt": 123, "scopes": ["a"]}}, "test")
    assert creds and creds["accessToken"] == "tok"
    assert creds["source"] == "test"
    assert oauth._extract({"nope": 1}, "test") is None


def test_token_valid_checks_expiry(monkeypatch):
    from birkin import oauth
    import time
    future = int(time.time() * 1000) + 3_600_000     # ms, +1h
    past = int(time.time() * 1000) - 1000
    assert oauth._token_valid({"accessToken": "t", "expiresAt": future}) is True
    assert oauth._token_valid({"accessToken": "t", "expiresAt": past}) is False
    # no expiry -> falls back to token presence
    assert oauth._token_valid({"accessToken": "t"}) is True
    assert oauth._token_valid({}) is False
