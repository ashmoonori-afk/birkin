"""Codex OAuth — birkin's own ChatGPT session.

The regression these tests exist for: birkin used to borrow the codex CLI's
credential, and refresh-token rotation then killed the user's `codex login`.
Anything here that touches ``~/.codex`` must stay read-only.
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from birkin import codex_oauth, providers


def _jwt(claims: dict) -> str:
    """A signature-less JWT — the module only ever decodes its own token."""
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def _token(*, expires_in: int = 3600, account: str = "acct-1") -> str:
    return _jwt({"exp": int(time.time()) + expires_in,
                 "https://api.openai.com/auth": {"chatgpt_account_id": account}})


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "birkin-home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    return tmp_path


# --- expiry ---------------------------------------------------------------

def test_expiry_uses_the_jwt_and_fails_toward_refresh(home):
    assert codex_oauth._is_expiring(_token(expires_in=3600), 120) is False
    assert codex_oauth._is_expiring(_token(expires_in=-1), 120) is True
    # inside the skew window
    assert codex_oauth._is_expiring(_token(expires_in=60), 120) is True
    # unreadable must refresh rather than be used
    assert codex_oauth._is_expiring("not-a-jwt", 120) is True
    assert codex_oauth._is_expiring("", 120) is True


def test_account_id_prefers_the_stored_value_then_the_claim(home):
    tok = _token(account="from-claim")
    assert codex_oauth.account_id(tok, {"account_id": "from-store"}) == "from-store"
    assert codex_oauth.account_id(tok, {}) == "from-claim"
    assert codex_oauth.account_id("garbage", None) == ""


# --- store ----------------------------------------------------------------

def test_store_round_trips_and_is_not_world_readable(home):
    assert codex_oauth.is_logged_in() is False
    assert codex_oauth.resolve_token() is None

    tok = _token()
    codex_oauth._write_store({"access_token": tok, "refresh_token": "r1",
                              "account_id": "acct-1"})
    assert codex_oauth.is_logged_in() is True
    assert codex_oauth.resolve_token() == tok

    path = codex_oauth.store_path()
    assert path.is_file()
    assert not list(path.parent.glob("*.tmp"))
    info = codex_oauth.status()
    assert info["logged_in"] is True
    assert info["account_id"] == "acct-1"
    assert info["expires_in_seconds"] > 0


def test_logout_removes_the_credential(home):
    codex_oauth._write_store({"access_token": _token(), "refresh_token": "r1"})
    assert codex_oauth.logout() is True
    assert codex_oauth.is_logged_in() is False
    assert codex_oauth.logout() is False


# --- refresh --------------------------------------------------------------

def test_resolve_token_refreshes_and_keeps_the_rotated_refresh_token(
        home, monkeypatch):
    """Rotation is the whole hazard: drop the new refresh token and the next
    call is locked out, exactly the failure this module exists to avoid."""
    fresh = _token(expires_in=3600)
    calls = []

    def fake_post(url, *, form=None, payload=None, timeout=20):
        calls.append(form)
        return 200, {"access_token": fresh, "refresh_token": "r2"}

    monkeypatch.setattr(codex_oauth, "_post", fake_post)
    codex_oauth._write_store({"access_token": _token(expires_in=-5),
                              "refresh_token": "r1", "account_id": "acct-1"})

    assert codex_oauth.resolve_token() == fresh
    assert calls[0]["grant_type"] == "refresh_token"
    assert calls[0]["refresh_token"] == "r1"

    stored = json.loads(codex_oauth.store_path().read_text(encoding="utf-8"))
    assert stored["tokens"]["refresh_token"] == "r2"
    assert stored["tokens"]["access_token"] == fresh

    # A second call is inside the validity window — no further network.
    assert codex_oauth.resolve_token() == fresh
    assert len(calls) == 1


def test_refresh_failure_is_raised_not_swallowed(home, monkeypatch):
    monkeypatch.setattr(codex_oauth, "_post",
                        lambda *a, **k: (400, {"error": "invalid_grant"}))
    codex_oauth._write_store({"access_token": _token(expires_in=-5),
                              "refresh_token": "r1"})
    with pytest.raises(codex_oauth.CodexAuthError) as exc:
        codex_oauth.resolve_token()
    assert "invalid_grant" in str(exc.value)
    assert "birkin auth codex login" in str(exc.value)


def test_refresh_without_a_token_tells_the_user_to_log_in(home):
    with pytest.raises(codex_oauth.CodexAuthError):
        codex_oauth.refresh("")


# --- the regression guard -------------------------------------------------

def test_nothing_here_ever_writes_the_codex_cli_credential(home, monkeypatch):
    """~/.codex must be read-only for birkin — writing it burns the CLI login."""
    codex_home = home / "codex-home"
    codex_home.mkdir()
    cli_auth = codex_home / "auth.json"
    original = json.dumps({"tokens": {"access_token": _token(),
                                      "refresh_token": "cli-r1",
                                      "account_id": "cli-acct"}})
    cli_auth.write_text(original, encoding="utf-8")

    monkeypatch.setattr(codex_oauth, "_post",
                        lambda *a, **k: (200, {"access_token": _token(),
                                               "refresh_token": "r2"}))
    codex_oauth.import_cli_tokens()
    codex_oauth._write_store({"access_token": _token(expires_in=-5),
                              "refresh_token": "r1"})
    codex_oauth.resolve_token()

    assert cli_auth.read_text(encoding="utf-8") == original
    assert codex_oauth.store_path() != cli_auth


def test_import_adopts_the_cli_tokens_without_touching_the_source(home):
    codex_home = home / "codex-home"
    codex_home.mkdir()
    tok = _token(account="cli-acct")
    (codex_home / "auth.json").write_text(json.dumps(
        {"tokens": {"access_token": tok, "refresh_token": "cli-r1"}}),
        encoding="utf-8")

    adopted = codex_oauth.import_cli_tokens()
    assert adopted["refresh_token"] == "cli-r1"
    assert adopted["account_id"] == "cli-acct"
    assert codex_oauth.is_logged_in() is True


def test_import_without_a_cli_login_is_a_clear_error(home):
    with pytest.raises(codex_oauth.CodexAuthError) as exc:
        codex_oauth.import_cli_tokens()
    assert "no codex CLI credential" in str(exc.value)


# --- headers --------------------------------------------------------------

def test_auth_headers_carry_the_first_party_identity(home):
    """Without originator/user-agent the Codex edge answers 403 regardless
    of whether the bearer token is good."""
    tok = _token(account="acct-9")
    codex_oauth._write_store({"access_token": tok, "refresh_token": "r1",
                              "account_id": "acct-9"})
    headers = codex_oauth.auth_headers(tok)
    assert headers["Authorization"] == f"Bearer {tok}"
    assert headers["originator"] == "codex_cli_rs"
    assert headers["User-Agent"].startswith("codex_cli_rs/")
    assert headers["ChatGPT-Account-ID"] == "acct-9"


def test_base_url_is_overridable(home, monkeypatch):
    assert codex_oauth.base_url() == codex_oauth.DEFAULT_BASE_URL
    monkeypatch.setenv("BIRKIN_CODEX_BASE_URL", "https://example.test/api/")
    assert codex_oauth.base_url() == "https://example.test/api"


# --- device login ---------------------------------------------------------

def test_device_login_polls_then_exchanges_and_persists(home, monkeypatch):
    tok = _token(account="acct-dev")
    seen = []

    def fake_post(url, *, form=None, payload=None, timeout=20):
        seen.append(url)
        if url == codex_oauth._DEVICE_CODE_URL:
            return 200, {"user_code": "ABCD-1234",
                         "device_auth_id": "dev-1", "interval": 1}
        if url == codex_oauth._DEVICE_TOKEN_URL:
            # not approved yet, then approved
            if seen.count(codex_oauth._DEVICE_TOKEN_URL) == 1:
                return 404, {}
            return 200, {"authorization_code": "code-1",
                         "code_verifier": "verifier-1"}
        return 200, {"access_token": tok, "refresh_token": "r-dev"}

    monkeypatch.setattr(codex_oauth, "_post", fake_post)
    lines: list[str] = []
    tokens = codex_oauth.device_login(emit=lines.append, poll_seconds=0,
                                      sleep=lambda _s: None)

    assert tokens["access_token"] == tok
    assert tokens["refresh_token"] == "r-dev"
    assert tokens["account_id"] == "acct-dev"
    assert codex_oauth.is_logged_in() is True
    assert any("ABCD-1234" in line for line in lines)
    assert seen.count(codex_oauth._DEVICE_TOKEN_URL) == 2


def test_device_login_surfaces_a_polling_error(home, monkeypatch):
    def fake_post(url, *, form=None, payload=None, timeout=20):
        if url == codex_oauth._DEVICE_CODE_URL:
            return 200, {"user_code": "X", "device_auth_id": "d", "interval": 1}
        return 500, {"error": "boom"}

    monkeypatch.setattr(codex_oauth, "_post", fake_post)
    with pytest.raises(codex_oauth.CodexAuthError) as exc:
        codex_oauth.device_login(emit=lambda _m: None, poll_seconds=0,
                                 sleep=lambda _s: None)
    assert "polling failed" in str(exc.value)


# --- Responses wire format ------------------------------------------------

def test_responses_text_reads_streamed_deltas():
    raw = (
        'data: {"type":"response.output_text.delta","delta":"he"}\n\n'
        'data: {"type":"response.output_text.delta","delta":"llo"}\n\n'
        'data: [DONE]\n\n'
    )
    assert providers._responses_text(raw) == "hello"


def test_responses_text_falls_back_to_the_terminal_event():
    """Some replies arrive whole, with no token-by-token deltas at all."""
    completed = {"type": "response.completed", "response": {"output": [
        {"type": "message", "content": [
            {"type": "output_text", "text": "whole answer"}]}]}}
    raw = f"event: response.completed\ndata: {json.dumps(completed)}\n\n"
    assert providers._responses_text(raw) == "whole answer"


def test_responses_text_handles_a_buffered_json_reply():
    body = {"output": [{"type": "message", "content": [
        {"type": "output_text", "text": "json answer"}]}]}
    assert providers._responses_text(json.dumps(body)) == "json answer"


def test_responses_text_is_empty_when_there_is_nothing_to_read():
    assert providers._responses_text("") == ""
    assert providers._responses_text("data: not-json\n\n") == ""


# --- completer ------------------------------------------------------------

def test_oauth_completer_reports_a_missing_login_instead_of_crashing(
        home, monkeypatch):
    monkeypatch.setattr(codex_oauth, "resolve_token", lambda: None)
    out = providers.codex_oauth_completer()("hi")
    assert "not logged in" in out
    assert "birkin auth codex login" in out
