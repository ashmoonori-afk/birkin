"""P2-2: prompt caching (already implemented) — pin it so it can't regress.

Anthropic prompt caching gives ~90% cheaper cache reads on the stable
prefix. birkin already marks the system block and the tool list as
ephemeral-cacheable; these tests guard that from silent removal.
"""

from __future__ import annotations

import io

from birkin.llm import LLMClient


def _capture_payload(monkeypatch):
    c = LLMClient(provider="anthropic", model="m", api_key="k",
                  base_url="https://x")
    seen: dict = {}

    def fake_post(url, headers, payload, *, stream, timeout=300.0):
        seen["payload"] = payload
        # minimal well-formed anthropic SSE so _read_anthropic_stream returns
        return io.BytesIO(
            b'data: {"type":"message_start"}\n'
            b'data: {"type":"message_stop"}\n')
    monkeypatch.setattr(c, "_post", fake_post)
    return c, seen


def test_system_block_is_cacheable(monkeypatch):
    c, seen = _capture_payload(monkeypatch)
    c._anthropic_complete("PERSONA + MEMORY", [], None, "m", None)
    blocks = seen["payload"]["system"]
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}
    assert blocks[-1]["text"] == "PERSONA + MEMORY"


def test_tool_list_is_cacheable(monkeypatch):
    c, seen = _capture_payload(monkeypatch)
    tools = [{"name": "a", "input_schema": {}},
             {"name": "b", "input_schema": {}}]
    c._anthropic_complete("sys", [], tools, "m", None)
    sent = seen["payload"]["tools"]
    assert sent[-1]["cache_control"] == {"type": "ephemeral"}   # cache the list
    assert "cache_control" not in sent[0]                       # one breakpoint
