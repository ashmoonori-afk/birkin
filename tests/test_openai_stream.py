"""P1-1b: OpenAI-compatible providers stream token deltas."""

from __future__ import annotations

from birkin.llm import LLMClient


def _sse(*objs) -> list[bytes]:
    import json
    lines = [f"data: {json.dumps(o)}".encode() for o in objs]
    lines.append(b"data: [DONE]")
    return lines


def test_text_deltas_stream_and_join():
    got: list[str] = []
    resp = _sse(
        {"choices": [{"delta": {"content": "안녕"}}]},
        {"choices": [{"delta": {"content": "하세요"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    )
    out = LLMClient._read_openai_stream(resp, got.append)
    assert got == ["안녕", "하세요"]                 # streamed as they arrive
    assert out["content"] == [{"type": "text", "text": "안녕하세요"}]
    assert out["stop_reason"] == "end_turn"


def test_tool_call_deltas_reassemble_by_index():
    got: list[str] = []
    resp = _sse(
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1",
             "function": {"name": "memory_search", "arguments": '{"que'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": 'ry":"x"}'}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    )
    out = LLMClient._read_openai_stream(resp, got.append)
    assert got == []                                # no text this turn
    assert out["stop_reason"] == "tool_use"
    tu = out["content"][0]
    assert tu["type"] == "tool_use" and tu["name"] == "memory_search"
    assert tu["input"] == {"query": "x"}            # fragments reassembled
    assert tu["id"] == "call_1"


def test_abort_stops_consuming():
    class _Abort:
        def is_set(self):
            return True
    got: list[str] = []
    resp = _sse({"choices": [{"delta": {"content": "should-not-appear"}}]})
    out = LLMClient._read_openai_stream(resp, got.append, _Abort())
    assert out["stop_reason"] == "aborted"
    assert got == []


def test_malformed_lines_are_skipped():
    got: list[str] = []
    resp = [b"", b": comment", b"data: not-json",
            b'data: {"choices":[{"delta":{"content":"ok"}}]}', b"data: [DONE]"]
    out = LLMClient._read_openai_stream(resp, got.append)
    assert got == ["ok"]
    assert out["content"] == [{"type": "text", "text": "ok"}]
