"""More offline coverage for llm.py: OpenAI mapping, _post retry, Anthropic
payload shape (incl. prompt caching), and the OpenAI non-streaming complete()."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from birkin import llm as llm_mod
from birkin.llm import LLMClient, LLMError


# ---------------- _to_openai_messages mapping ----------------

def test_openai_message_mapping_text_and_tool_use_and_result():
    system = "SYS"
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "calling"},
            {"type": "tool_use", "id": "t1", "name": "echo", "input": {"x": 1}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "echoed", "is_error": False},
        ]},
    ]
    out = llm_mod._to_openai_messages(system, messages)
    # first message is the system
    assert out[0] == {"role": "system", "content": "SYS"}
    # user msg, then assistant with tool_calls, then tool role with tool_call_id
    roles = [m["role"] for m in out]
    assert roles == ["system", "user", "assistant", "tool"]
    tool_msg = out[-1]
    assert tool_msg["tool_call_id"] == "t1"
    assert tool_msg["content"] == "echoed"
    # assistant tool_calls argument is JSON-encoded
    asst = out[2]
    assert asst["tool_calls"][0]["function"]["name"] == "echo"
    assert json.loads(asst["tool_calls"][0]["function"]["arguments"]) == {"x": 1}


def test_openai_message_mapping_handles_string_content():
    out = llm_mod._to_openai_messages("", [{"role": "user", "content": "plain"}])
    assert out[-1] == {"role": "user", "content": "plain"}


# ---------------- _post retry/backoff ----------------

def test_post_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    class FakeResp:
        status = 200
        def read(self): return b'{"ok":true}'

    def flaky_urlopen(req, timeout=300):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("transient")
        return FakeResp()

    # no sleeping in tests
    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", flaky_urlopen)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda *_: None)

    c = LLMClient(provider="anthropic", model="m", api_key="k", base_url="")
    resp = c._post("https://example/x", {"x-api-key": "k"},
                   {"foo": "bar"}, stream=False)
    assert resp.read() == b'{"ok":true}'
    assert calls["n"] == 3  # retried twice, succeeded on the third try


def test_post_gives_up_after_max_attempts(monkeypatch):
    def always_fail(req, timeout=300):
        raise urllib.error.URLError("dead")

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", always_fail)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda *_: None)
    c = LLMClient(provider="anthropic", model="m", api_key="k", base_url="")
    with pytest.raises(LLMError):
        c._post("https://example/x", {}, {}, stream=False)


# ---------------- Anthropic payload shape (incl. prompt caching) ----------------

def test_anthropic_payload_marks_system_and_last_tool_cache_control(monkeypatch):
    captured = {}

    class FakeStreamResp:
        def __iter__(self):
            # send a minimal end_turn event so the stream parser is happy
            payload = {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}
            yield ("data: " + json.dumps(payload)).encode()

    def fake_post(self, url, headers, payload, *, stream, timeout=300.0):
        captured["payload"] = payload
        captured["headers"] = headers
        return FakeStreamResp()

    monkeypatch.setattr(LLMClient, "_post", fake_post)
    c = LLMClient(provider="anthropic", model="m", api_key="k", base_url="")
    c.complete(system="hello", messages=[
        {"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        tools=[{"name": "t1", "description": "d", "input_schema": {}},
               {"name": "t2", "description": "d", "input_schema": {}}])
    p = captured["payload"]
    # system arrives as a list of content blocks with cache_control on the system block
    assert isinstance(p["system"], list)
    assert p["system"][0]["cache_control"]["type"] == "ephemeral"
    # the last tool gets cache_control too
    assert p["tools"][-1]["cache_control"]["type"] == "ephemeral"
    # headers carry anthropic auth + version
    assert captured["headers"]["x-api-key"] == "k"
    assert "anthropic-version" in captured["headers"]


# ---------------- OpenAI non-streaming complete() ----------------

def test_openai_complete_parses_text_and_tool_calls(monkeypatch):
    fake_body = {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "content": "calling a tool",
                "tool_calls": [{
                    "id": "tc1",
                    "function": {"name": "echo",
                                 "arguments": '{"x": 42}'},
                }],
            },
        }],
    }

    class FakeResp:
        def read(self): return json.dumps(fake_body).encode()

    monkeypatch.setattr(LLMClient, "_post",
                        lambda self, url, headers, payload, *, stream, timeout=300.0: FakeResp())
    c = LLMClient(provider="openai", model="gpt-4o", api_key="k", base_url="")
    res = c.complete(system="", messages=[
        {"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        tools=[{"name": "echo", "description": "d", "input_schema": {}}])
    types_ = [b["type"] for b in res["content"]]
    assert "text" in types_ and "tool_use" in types_
    tool = [b for b in res["content"] if b["type"] == "tool_use"][0]
    assert tool["name"] == "echo" and tool["input"] == {"x": 42}
    assert res["stop_reason"] == "tool_use"


def test_unknown_provider_raises():
    c = LLMClient(provider="bogus", model="m", api_key="k", base_url="")
    with pytest.raises(LLMError):
        c.complete(system="", messages=[
            {"role": "user", "content": [{"type": "text", "text": "hi"}]}],
            tools=None)
