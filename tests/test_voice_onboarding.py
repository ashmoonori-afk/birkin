"""Voice-mode onboarding and scoped conversation-style coverage."""

from __future__ import annotations

import builtins
import importlib
from collections.abc import Iterator
from typing import Any

from birkin.cli import build_parser

from birkin import config, menu


def _choices(values: list[int]) -> Iterator[int]:
    return iter(values)


def test_voice_setup_persists_wake_style_and_voice(
    monkeypatch: Any,
) -> None:
    selected = _choices([1, 2, 3])
    monkeypatch.setattr(
        menu,
        "select",
        lambda *_args, **_kwargs: next(selected),
    )

    args = build_parser().parse_args(["voice", "setup"])

    assert args.func(args) == 0
    voice = config.load_config()["voice"]
    assert voice["wake_phrase"] == "Birkin"
    assert voice["conversation_style"] == "curious"
    assert voice["tts_voice"] == "onyx"
    assert voice["onboarding_complete"] is True


def test_voice_style_wraps_only_the_gateway_turn() -> None:
    styles = importlib.import_module("birkin.voice.styles")

    styled = styles.format_voice_command("status", "concise")

    assert styled.startswith("status\n\n")
    assert '<voice-response-style id="concise">' in styled
    assert styled.endswith("</voice-response-style>")
    assert styles.format_voice_command("status", "") == "status"


def test_voice_setup_reprompts_invalid_custom_wake_phrase(
    monkeypatch: Any,
) -> None:
    selected = _choices([3, 0, 0])
    answers = iter(["!!!", "Computer"])
    calls = 0

    def fake_input(_prompt: str) -> str:
        nonlocal calls
        calls += 1
        return next(answers)

    monkeypatch.setattr(
        menu,
        "select",
        lambda *_args, **_kwargs: next(selected),
    )
    monkeypatch.setattr(builtins, "input", fake_input)

    args = build_parser().parse_args(["voice", "setup"])

    assert args.func(args) == 0
    assert calls == 2
    assert config.load_config()["voice"]["wake_phrase"] == "Computer"


def test_voice_start_runs_first_setup_before_daemon(
    monkeypatch: Any,
) -> None:
    onboarding = importlib.import_module("birkin.voice.onboarding")
    daemon = importlib.import_module("birkin.voice.daemon")
    events: list[str] = []

    monkeypatch.setattr(onboarding, "is_complete", lambda: False)
    monkeypatch.setattr(
        onboarding,
        "run",
        lambda: events.append("setup") or 0,
    )
    monkeypatch.setattr(
        daemon,
        "start_daemon",
        lambda _args: events.append("start") or 0,
    )

    args = build_parser().parse_args(["voice", "start"])

    assert args.func(args) == 0
    assert events == ["setup", "start"]
