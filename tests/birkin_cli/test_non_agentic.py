"""Tests for the Nous-Birkin-3/4 non-agentic warning detector.

Prior to this check, the warning fired on any model whose name contained
``"birkin"`` anywhere (case-insensitive). That false-positived on unrelated
local Modelfiles such as ``birkin-brain:qwen3-14b-ctx16k`` — a tool-capable
Qwen3 wrapper that happens to live under the "birkin" tag namespace.

``is_nous_birkin_non_agentic`` should only match the actual Nous Research
Birkin-3 / Birkin-4 chat family.
"""

from __future__ import annotations

import pytest

from birkin_cli.model_switch import (
    _BIRKIN_MODEL_WARNING,
    _check_birkin_model_warning,
    is_nous_birkin_non_agentic,
)


@pytest.mark.parametrize(
    "model_name",
    [
        "NousResearch/Hermes-3-Llama-3.1-70B",
        "NousResearch/Hermes-3-Llama-3.1-405B",
        "birkin-3",
        "Birkin-3",
        "birkin-4",
        "hermes-4-405b",
        "birkin_4_70b",
        "openrouter/hermes3:70b",
        "openrouter/nousresearch/hermes-4-405b",
        "NousResearch/Hermes3",
        "birkin-3.1",
    ],
)
def test_matches_real_nous_birkin_chat_models(model_name: str) -> None:
    assert is_nous_birkin_non_agentic(model_name), (
        f"expected {model_name!r} to be flagged as Nous Birkin 3/4"
    )
    assert _check_birkin_model_warning(model_name) == _BIRKIN_MODEL_WARNING


@pytest.mark.parametrize(
    "model_name",
    [
        # Kyle's local Modelfile — qwen3:14b under a custom tag
        "birkin-brain:qwen3-14b-ctx16k",
        "birkin-brain:qwen3-14b-ctx32k",
        "birkin-honcho:qwen3-8b-ctx8k",
        # Plain unrelated models
        "qwen3:14b",
        "qwen3-coder:30b",
        "qwen2.5:14b",
        "claude-opus-4-6",
        "anthropic/claude-sonnet-4.5",
        "gpt-5",
        "openai/gpt-4o",
        "google/gemini-2.5-flash",
        "deepseek-chat",
        # Non-chat Birkin models we don't warn about
        "birkin-llm-2",
        "hermes2-pro",
        "nous-birkin-2-mistral",
        # Edge cases
        "",
        "birkin",  # bare "birkin" isn't the 3/4 family
        "birkin-brain",
        "brain-birkin-3-impostor",  # "3" not preceded by /: boundary
    ],
)
def test_does_not_match_unrelated_models(model_name: str) -> None:
    assert not is_nous_birkin_non_agentic(model_name), (
        f"expected {model_name!r} NOT to be flagged as Nous Birkin 3/4"
    )
    assert _check_birkin_model_warning(model_name) == ""


def test_none_like_inputs_are_safe() -> None:
    assert is_nous_birkin_non_agentic("") is False
    # Defensive: the helper shouldn't crash on None-ish falsy input either.
    assert _check_birkin_model_warning("") == ""
