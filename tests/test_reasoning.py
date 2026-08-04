"""Multi-format reasoning extraction from provider message dicts.

Providers disagree on where thinking lives: ``reasoning`` (DeepSeek/Qwen),
``reasoning_content`` (Moonshot), ``reasoning_details`` (OpenRouter unified),
typed ``thinking`` blocks inside a content list, or inline ``<think>`` tags.
Without one extractor the text is silently dropped -- or worse, shown.
"""

from __future__ import annotations

from birkin.reasoning import extract_reasoning


def test_direct_reasoning_field() -> None:
    assert extract_reasoning({"reasoning": "step 1"}) == "step 1"


def test_reasoning_content_alternative_field() -> None:
    assert extract_reasoning({"reasoning_content": "alt"}) == "alt"


def test_duplicate_fields_are_not_repeated() -> None:
    assert extract_reasoning(
        {"reasoning": "same", "reasoning_content": "same"}) == "same"


def test_reasoning_details_array_openrouter_unified() -> None:
    msg = {"reasoning_details": [
        {"type": "reasoning.summary", "summary": "s1"},
        {"type": "reasoning.text", "text": "s2"},
    ]}
    out = extract_reasoning(msg)
    assert out is not None
    assert "s1" in out and "s2" in out


def test_thinking_block_inside_content_list() -> None:
    msg = {"content": [{"type": "thinking", "thinking": "deep"},
                       {"type": "text", "text": "answer"}]}
    assert extract_reasoning(msg) == "deep"


def test_inline_think_tag_is_the_fallback() -> None:
    assert extract_reasoning({"content": "<think>hidden</think>visible"}) == "hidden"


def test_structured_reasoning_wins_over_inline() -> None:
    msg = {"reasoning": "real", "content": "<think>x</think>y"}
    assert extract_reasoning(msg) == "real"


def test_message_without_reasoning_returns_none() -> None:
    assert extract_reasoning({"content": "plain text"}) is None
    assert extract_reasoning({}) is None
