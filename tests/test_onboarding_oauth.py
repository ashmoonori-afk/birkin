"""P1-4: onboarding welcome + first-touch smoke coverage (oauth was untested)."""

from __future__ import annotations


def test_onboarding_defaults_provider_menu_to_codex_cli(
        tmp_path, monkeypatch):
    from birkin import config, models, onboarding, provider_onboarding

    cfg = dict(config.DEFAULT_CONFIG)
    saved = {}

    monkeypatch.setattr(onboarding.config, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(
        onboarding.config, "config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(
        onboarding.config, "save_config", lambda value: saved.update(value))
    monkeypatch.setattr(onboarding.persona, "seed_default", lambda: False)
    monkeypatch.setattr(onboarding, "_ask", lambda _label, default="": default)
    monkeypatch.setattr(
        onboarding, "_ask_yesno", lambda _label, default=False: False)

    def select(_prompt, options, default=0):
        assert options[default] == "codex-cli"
        return default

    monkeypatch.setattr(onboarding.menu, "select", select)
    monkeypatch.setattr(
        provider_onboarding,
        "probe_codex",
        lambda: provider_onboarding.CodexProviderStatus(
            usable=True,
            path="/fake/codex",
            issue=None,
        ),
    )

    def pick_interactive(value):
        assert value["provider"] == "codex-cli"
        return None

    monkeypatch.setattr(models, "pick_interactive", pick_interactive)

    assert onboarding.run() == 0
    assert saved["provider"] == "codex-cli"


def test_onboarding_retries_codex_probe_without_restarting_wizard(
        tmp_path, monkeypatch):
    from birkin import config, models, onboarding, provider_onboarding

    cfg = dict(config.DEFAULT_CONFIG)
    saved = {}
    probes = iter(
        [
            provider_onboarding.CodexProviderStatus(
                False,
                None,
                provider_onboarding.CodexProbeIssue.NOT_FOUND,
            ),
            provider_onboarding.CodexProviderStatus(True, "/fake/codex", None),
        ],
    )
    probe_count = 0
    ask_count = 0
    model_count = 0

    monkeypatch.setattr(onboarding.config, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(
        onboarding.config,
        "config_path",
        lambda: tmp_path / "config.json",
    )
    monkeypatch.setattr(
        onboarding.config,
        "save_config",
        lambda value: saved.update(value),
    )
    monkeypatch.setattr(onboarding.persona, "seed_default", lambda: False)
    monkeypatch.setattr(
        onboarding,
        "_ask_yesno",
        lambda _label, default=False: False,
    )

    def ask(_label, default=""):
        nonlocal ask_count
        ask_count += 1
        return default

    def select(_prompt, options, default=0):
        if options == ["codex-cli", "claude-cli", "anthropic", "openai"]:
            return 0
        return 0

    def probe():
        nonlocal probe_count
        probe_count += 1
        return next(probes)

    def pick_interactive(_value):
        nonlocal model_count
        model_count += 1
        return None

    monkeypatch.setattr(onboarding, "_ask", ask)
    monkeypatch.setattr(onboarding.menu, "select", select)
    monkeypatch.setattr(provider_onboarding, "probe_codex", probe)
    monkeypatch.setattr(models, "pick_interactive", pick_interactive)

    assert onboarding.run() == 0
    assert saved["provider"] == "codex-cli"
    assert probe_count == 2
    assert model_count == 1
    assert ask_count == 2


def test_onboarding_missing_codex_can_choose_another_provider(
        tmp_path, monkeypatch, capsys):
    from birkin import config, models, onboarding, provider_onboarding

    cfg = dict(config.DEFAULT_CONFIG)
    saved = {}
    provider_choices = iter([0, 1])

    monkeypatch.setattr(onboarding.config, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(
        onboarding.config,
        "config_path",
        lambda: tmp_path / "config.json",
    )
    monkeypatch.setattr(
        onboarding.config,
        "save_config",
        lambda value: saved.update(value),
    )
    monkeypatch.setattr(onboarding.persona, "seed_default", lambda: False)
    monkeypatch.setattr(onboarding, "_ask", lambda _label, default="": default)
    monkeypatch.setattr(
        onboarding,
        "_ask_yesno",
        lambda _label, default=False: False,
    )
    monkeypatch.setattr(
        provider_onboarding,
        "probe_codex",
        lambda: provider_onboarding.CodexProviderStatus(
            False,
            None,
            provider_onboarding.CodexProbeIssue.NOT_FOUND,
        ),
    )

    def select(_prompt, options, default=0):
        if options == ["codex-cli", "claude-cli", "anthropic", "openai"]:
            return next(provider_choices)
        return 1

    monkeypatch.setattr(onboarding.menu, "select", select)
    monkeypatch.setattr(models, "pick_interactive", lambda _value: None)

    assert onboarding.run() == 0
    assert saved["provider"] == "claude-cli"
    output = capsys.readouterr().out
    assert "Codex CLI가 설치되어 있지 않습니다." in output
    assert "https://chatgpt.com/codex/install." in output


def test_onboarding_api_key_command_uses_powershell_session_scope() -> None:
    from birkin.onboarding import _api_key_environment_command

    command = _api_key_environment_command("OPENAI_API_KEY", "win32")

    assert command == '$env:OPENAI_API_KEY = "<API key>"'
    assert "setx" not in command


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
