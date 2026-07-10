"""claude-cli streaming: _run_claude parses --output-format stream-json and
forwards assistant text deltas to on_text as they arrive (not one blob at end).

The subprocess boundary (_run_cli_capture) is mocked to replay a canned JSONL
event stream through the on_line hook, so no real `claude` is spawned.
"""

from birkin.llm import LLMClient

USER = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


def _client():
    return LLMClient(provider="claude-cli", model="", api_key="cli", base_url="")


def _delta(text):
    return ('{"type":"stream_event","event":{"type":"content_block_delta",'
            '"index":0,"delta":{"type":"text_delta","text":%r}}}' % text
            ).replace("'", '"')


def test_claude_cli_streams_text_deltas(monkeypatch):
    lines = [
        '{"type":"system","subtype":"init"}',
        _delta("Hel"), _delta("lo, "), _delta("world"),
        '{"type":"assistant","message":{"content":[{"type":"text","text":"Hello, world"}]}}',
        '{"type":"result","subtype":"success","is_error":false,"result":"Hello, world"}',
    ]
    seen = {}

    def fake_capture(self, argv, prompt, abort=None, env=None, on_line=None):
        seen["argv"] = argv
        for ln in lines:
            if on_line:
                on_line(ln + "\n")
        return "\n".join(lines), "", False, False

    monkeypatch.setattr(LLMClient, "_run_cli_capture", fake_capture)
    got = []
    res = _client().complete(system="s", messages=USER, tools=[], on_text=got.append)

    assert "stream-json" in seen["argv"]                 # requested streaming
    assert got == ["Hel", "lo, ", "world"]               # per-delta, in order
    assert "".join(got) == "Hello, world"
    assert res["content"][0]["text"] == "Hello, world"   # return == streamed text


def test_claude_cli_falls_back_to_result_when_no_deltas(monkeypatch):
    # An older claude with no --include-partial-messages emits whole messages
    # only; we must still return the answer and print it once.
    lines = [
        '{"type":"system","subtype":"init"}',
        '{"type":"assistant","message":{"content":[{"type":"text","text":"Answer"}]}}',
        '{"type":"result","subtype":"success","result":"Answer"}',
    ]

    def fake_capture(self, argv, prompt, abort=None, env=None, on_line=None):
        for ln in lines:
            if on_line:
                on_line(ln + "\n")
        return "\n".join(lines), "", False, False

    monkeypatch.setattr(LLMClient, "_run_cli_capture", fake_capture)
    got = []
    res = _client().complete(system="s", messages=USER, tools=[], on_text=got.append)

    assert got == ["Answer"]                              # printed once at the end
    assert res["content"][0]["text"] == "Answer"


def test_claude_cli_abort_keeps_partial(monkeypatch):
    def fake_capture(self, argv, prompt, abort=None, env=None, on_line=None):
        if on_line:
            on_line(_delta("partial so far") + "\n")
        return "", "", False, True                        # aborted mid-stream

    monkeypatch.setattr(LLMClient, "_run_cli_capture", fake_capture)
    got = []
    res = _client().complete(system="s", messages=USER, tools=[], on_text=got.append)

    assert got == ["partial so far"]                      # partial not re-printed
    assert res["content"][0]["text"] == "partial so far"  # kept, not "(aborted)"


def test_claude_cli_skips_non_json_lines(monkeypatch):
    def fake_capture(self, argv, prompt, abort=None, env=None, on_line=None):
        for ln in ["Some warning to stdout", _delta("ok"),
                   '{"type":"result","result":"ok"}']:
            if on_line:
                on_line(ln + "\n")
        return "", "", False, False

    monkeypatch.setattr(LLMClient, "_run_cli_capture", fake_capture)
    got = []
    res = _client().complete(system="s", messages=USER, tools=[], on_text=got.append)

    assert got == ["ok"]                                  # non-JSON line ignored
    assert res["content"][0]["text"] == "ok"
