"""Reasoning wiring through the OpenAI-compatible completion path.

The extractor (birkin/reasoning.py) is only useful if the LLM client actually
routes provider reasoning through it: structured fields must surface on the
returned assistant message, and leaked <think> text must never reach the
visible content blocks.
"""

from __future__ import annotations

import json

from birkin.llm import _plain_client


class _Resp:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body


def _complete(monkeypatch, message: dict) -> dict:
    client = _plain_client({"provider": "openai", "model": "m",
                            "base_url": "http://invalid.localhost",
                            "max_tokens": 16}, "key")
    body = {"choices": [{"message": message, "finish_reason": "stop"}]}
    monkeypatch.setattr(
        client, "_post",
        lambda url, headers, payload, stream=False: _Resp(body))
    return client._openai_complete("", [], None, "m", None)


def test_structured_reasoning_is_attached_not_shown(monkeypatch) -> None:
    out = _complete(monkeypatch, {"content": "answer", "reasoning": "deep"})
    assert out.get("reasoning") == "deep"
    assert out["content"] == [{"type": "text", "text": "answer"}]


def test_inline_think_is_stripped_from_visible_text(monkeypatch) -> None:
    out = _complete(monkeypatch, {"content": "<think>hidden</think>visible"})
    assert out["content"] == [{"type": "text", "text": "visible"}]
    assert out.get("reasoning") == "hidden"


def test_message_without_reasoning_is_unchanged(monkeypatch) -> None:
    out = _complete(monkeypatch, {"content": "plain"})
    assert "reasoning" not in out
    assert out["content"] == [{"type": "text", "text": "plain"}]
