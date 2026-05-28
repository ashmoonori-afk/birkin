import json

from birkin.llm import LLMClient


def _ev(d):
    return ("data: " + json.dumps(d)).encode()


def test_stream_parses_text_and_parallel_tool_use():
    stream = [
        _ev({"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}),
        _ev({"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "Hi there"}}),
        _ev({"type": "content_block_stop", "index": 0}),
        _ev({"type": "content_block_start", "index": 1,
             "content_block": {"type": "tool_use", "id": "a", "name": "alpha"}}),
        _ev({"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": '{"x":'}}),
        _ev({"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": "1}"}}),
        _ev({"type": "content_block_stop", "index": 1}),
        _ev({"type": "content_block_start", "index": 2,
             "content_block": {"type": "tool_use", "id": "b", "name": "beta"}}),
        _ev({"type": "content_block_delta", "index": 2,
             "delta": {"type": "input_json_delta", "partial_json": '{"y":"z"}'}}),
        _ev({"type": "content_block_stop", "index": 2}),
        _ev({"type": "message_delta", "delta": {"stop_reason": "tool_use"}}),
    ]
    streamed = []
    res = LLMClient._read_anthropic_stream(iter(stream), streamed.append)

    assert "".join(streamed) == "Hi there"
    assert res["stop_reason"] == "tool_use"
    by_name = {b["name"]: b for b in res["content"] if b["type"] == "tool_use"}
    assert by_name["alpha"]["input"] == {"x": 1}
    assert by_name["beta"]["input"] == {"y": "z"}


def test_stream_text_only():
    stream = [
        _ev({"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}),
        _ev({"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "hello"}}),
        _ev({"type": "content_block_stop", "index": 0}),
        _ev({"type": "message_delta", "delta": {"stop_reason": "end_turn"}}),
    ]
    res = LLMClient._read_anthropic_stream(iter(stream), None)
    assert res["stop_reason"] == "end_turn"
    assert res["content"] == [{"type": "text", "text": "hello"}]


def test_stream_malformed_lines_ignored():
    stream = [b"data: not-json", b": comment", b"\n",
              _ev({"type": "content_block_start", "index": 0,
                   "content_block": {"type": "text"}}),
              _ev({"type": "content_block_delta", "index": 0,
                   "delta": {"type": "text_delta", "text": "ok"}})]
    res = LLMClient._read_anthropic_stream(iter(stream), None)
    assert res["content"][0]["text"] == "ok"
