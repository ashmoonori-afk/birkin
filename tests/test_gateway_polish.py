"""Approved Telegram results receive an isolated Claude editing pass."""

from __future__ import annotations

import copy
from collections.abc import Callable

from birkin import config, providers
from birkin.gateway import core
from birkin.gateway import polish
from birkin.gateway.channels import build_channels
from birkin.gateway.channels import polished_telegram


class _DraftGateway(core.Gateway):
    def __init__(self) -> None:
        pass

    @property
    def pending_hard_restart(self) -> bool:
        return False

    def do_hard_restart(self) -> None:
        raise AssertionError("hard restart was not requested")

    def handle(
        self,
        channel: str,
        chat_id: str,
        text: str,
        on_text: Callable[[str], None] | None = None,
        workflow_id: str | None = None,
    ) -> str:
        return "초안: SPY $741"


def test_enabled_telegram_uses_polishing_channel() -> None:
    # Given
    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["channels"]["http"]["enabled"] = False
    cfg["channels"]["telegram"].update({
        "enabled": True,
        "token": "test-token",
        "allowed_chat_ids": ["42"],
    })

    # When
    built = build_channels(cfg)

    # Then
    assert [type(channel).__name__ for channel in built] == [
        "PolishedTelegramChannel"
    ]


def test_approved_channel_proxy_returns_polished_reply(monkeypatch) -> None:
    # Given
    seen: list[tuple[str, str]] = []

    def fake_polish(reply: str, active_cfg: dict[str, str]) -> str:
        seen.append((reply, active_cfg["morpheus_provider"]))
        return "윤문: SPY $741"

    monkeypatch.setattr(
        polished_telegram,
        "polish_telegram_reply",
        fake_polish,
    )
    proxy = polished_telegram._PolishingGateway(
        _DraftGateway(),
        {"morpheus_provider": "claude-cli"},
    )

    # When
    result = proxy.handle(
        "telegram",
        "42",
        "주식시장 분석",
        workflow_id="approval-1",
    )

    # Then
    assert result == "윤문: SPY $741"
    assert seen == [("초안: SPY $741", "claude-cli")]


def test_polisher_uses_configured_claude_without_losing_draft(
    monkeypatch,
) -> None:
    # Given
    seen: list[tuple[str, str | None, int, str]] = []

    def fake_factory(
        provider: str,
        *,
        model: str | None,
        cfg: dict,
        timeout: int,
    ):
        def complete(prompt: str) -> str:
            draft = prompt.split("<draft>\n", 1)[1].split("\n</draft>", 1)[0]
            seen.append((provider, model, timeout, draft))
            return "윤문: SPY $741"

        return complete

    monkeypatch.setattr(polish.providers, "get_completer", fake_factory)
    cfg = {
        "gateway_polish_provider": "claude-cli",
        "gateway_polish_model": "sonnet",
        "gateway_polish_timeout": 45,
    }

    # When
    result = polish.polish_telegram_reply("초안: SPY $741", cfg)

    # Then
    assert result == "윤문: SPY $741"
    assert seen == [("claude-cli", "sonnet", 45, "초안: SPY $741")]


def test_polisher_reuses_morpheus_claude_configuration(monkeypatch) -> None:
    # Given
    seen: list[tuple[str, str | None]] = []

    def fake_factory(
        provider: str,
        *,
        model: str | None,
        cfg: dict[str, str],
        timeout: int,
    ) -> providers.Completer:
        del cfg, timeout
        seen.append((provider, model))
        return lambda _prompt: "윤문: SPY $741"

    monkeypatch.setattr(polish.providers, "get_completer", fake_factory)

    # When
    result = polish.polish_telegram_reply(
        "초안: SPY $741",
        {
            "morpheus_provider": "claude-cli",
            "morpheus_model": "sonnet",
        },
    )

    # Then
    assert result == "윤문: SPY $741"
    assert seen == [("claude-cli", "sonnet")]


def test_polisher_rejects_candidate_that_drops_financial_facts(
    monkeypatch,
) -> None:
    # Given
    original = "SPY 기준가 $741\n출처: https://example.com/spy"
    monkeypatch.setattr(
        polish.providers,
        "get_completer",
        lambda *_args, **_kwargs: lambda _prompt: "SPY를 추천합니다.",
    )

    # When
    result = polish.polish_telegram_reply(
        original,
        {"gateway_polish_provider": "claude-cli"},
    )

    # Then
    assert result == original


def test_polisher_accepts_duplicate_fact_deduplication(monkeypatch) -> None:
    # Given
    original = "SPY 기준가 $741입니다. 다시 말해 기준가는 $741입니다."
    candidate = "SPY 기준가는 $741입니다."
    monkeypatch.setattr(
        polish.providers,
        "get_completer",
        lambda *_args, **_kwargs: lambda _prompt: candidate,
    )

    # When
    result = polish.polish_telegram_reply(
        original,
        {"gateway_polish_provider": "claude-cli"},
    )

    # Then
    assert result == candidate


def test_polisher_reports_provider_failure_and_preserves_draft(
    monkeypatch,
    capsys,
) -> None:
    # Given
    original = "SPY 기준가는 $741입니다."
    monkeypatch.setattr(
        polish.providers,
        "get_completer",
        lambda *_args, **_kwargs: lambda _prompt: (
            "[provider-error] claude: OAuth session expired"
        ),
    )

    # When
    result = polish.polish_telegram_reply(
        original,
        {"gateway_polish_provider": "claude-cli"},
    )

    # Then
    assert result == original
    assert "polish skipped" in capsys.readouterr().out
