"""claude-cli streaming: _run_claude parses --output-format stream-json and
forwards assistant text deltas to on_text as they arrive (not one blob at end).

The subprocess boundary (_run_cli_capture) is mocked to replay a canned JSONL
event stream through the on_line hook, so no real `claude` is spawned.
"""

import json
from pathlib import Path

import pytest

from birkin.llm import LLMClient, LLMError, _plain_client

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


def test_read_only_claude_cli_disables_tools(monkeypatch):
    seen = {}

    def fake_capture(self, argv, prompt, abort=None, env=None, on_line=None):
        seen["argv"] = argv
        return '{"type":"result","result":"ok"}', "", False, False

    monkeypatch.setattr(LLMClient, "_run_cli_capture", fake_capture)
    client = _client()
    client.cli_access = "read-only"
    client._run_claude("prompt", "", None)
    assert "--tools" in seen["argv"]
    assert seen["argv"][seen["argv"].index("--tools") + 1] == ""
    assert "--permission-mode" not in seen["argv"]
    assert "--safe-mode" in seen["argv"]
    assert "--no-session-persistence" in seen["argv"]


def test_enforced_claude_cli_uses_only_birkin_mcp_tools(monkeypatch):
    seen = {}

    def fake_capture(self, argv, prompt, abort=None, env=None, on_line=None):
        seen["argv"] = argv
        index = argv.index("--mcp-config")
        seen["mcp_path"] = Path(argv[index + 1])
        seen["mcp"] = json.loads(
            seen["mcp_path"].read_text(encoding="utf-8"))
        return '{"type":"result","result":"ok"}', "", False, False

    monkeypatch.setattr(LLMClient, "_run_cli_capture", fake_capture)
    client = _client()
    client.egress_enforced = True
    client._run_claude("prompt", "", None)

    argv = seen["argv"]
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--allowedTools") + 1] == "mcp__birkin__*"
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in argv
    assert "--disable-slash-commands" in argv
    assert "--no-chrome" in argv
    assert "--no-session-persistence" in argv
    assert "--dangerously-skip-permissions" not in argv
    assert set(seen["mcp"]["mcpServers"]) == {"birkin"}
    assert not seen["mcp_path"].exists()


def test_plain_client_propagates_enforced_egress():
    client = _plain_client(
        {
            "provider": "claude-cli",
            "model": "claude-code",
            "egress": {"enabled": True, "enforced": True},
        },
        "",
    )

    assert client.egress_enforced is True


def test_read_only_codex_cli_sets_read_only_sandbox(monkeypatch):
    seen = {}

    def fake_capture(self, argv, prompt, abort=None, env=None, on_line=None):
        seen["argv"] = argv
        return "", "", False, False

    monkeypatch.setattr(LLMClient, "_run_cli_capture", fake_capture)
    client = LLMClient(provider="codex-cli", model="", api_key="cli",
                       base_url="", cli_access="read-only")
    client._run_codex("prompt", "", None)
    assert "--sandbox" in seen["argv"]
    assert seen["argv"][seen["argv"].index("--sandbox") + 1] == "read-only"
    assert "sandbox_workspace_write.network_access=false" in seen["argv"]


def test_workspace_codex_cli_sets_network_policy(monkeypatch):
    seen = {}

    def fake_capture(self, argv, prompt, abort=None, env=None, on_line=None):
        seen["argv"] = argv
        return "", "", False, False

    monkeypatch.setattr(LLMClient, "_run_cli_capture", fake_capture)
    client = LLMClient(
        provider="codex-cli",
        model="",
        api_key="cli",
        base_url="",
        cli_network_access=True,
    )
    client._run_codex("prompt", "", None)

    assert "--sandbox" in seen["argv"]
    assert seen["argv"][seen["argv"].index("--sandbox") + 1] == "workspace-write"
    assert "sandbox_workspace_write.network_access=true" in seen["argv"]


def test_workspace_codex_cli_supports_offline_override(monkeypatch):
    seen = {}

    def fake_capture(self, argv, prompt, abort=None, env=None, on_line=None):
        seen["argv"] = argv
        return "", "", False, False

    monkeypatch.setattr(LLMClient, "_run_cli_capture", fake_capture)
    client = LLMClient(
        provider="codex-cli",
        model="",
        api_key="cli",
        base_url="",
        cli_network_access=False,
    )
    client._run_codex("prompt", "", None)

    assert "sandbox_workspace_write.network_access=false" in seen["argv"]


def test_codex_cli_adds_birkin_mcp_only_when_enabled(monkeypatch):
    seen = {}

    def fake_capture(self, argv, prompt, abort=None, env=None, on_line=None):
        seen["argv"] = argv
        return "", "", False, False

    monkeypatch.setattr(LLMClient, "_run_cli_capture", fake_capture)
    client = LLMClient(provider="codex-cli", model="", api_key="cli",
                       base_url="")
    client.birkin_mcp = True
    client._run_codex("prompt", "", None)

    assert any("mcp_servers.birkin.command" in arg for arg in seen["argv"])
    assert any("mcp_servers.birkin.args" in arg for arg in seen["argv"])


def test_codex_cli_timeout_raises(monkeypatch):
    def fake_capture(self, argv, prompt, abort=None, env=None, on_line=None):
        return "", "", True, False

    monkeypatch.setattr(LLMClient, "_run_cli_capture", fake_capture)
    client = LLMClient(provider="codex-cli", model="", api_key="cli",
                       base_url="", cli_timeout=7)

    with pytest.raises(LLMError, match="timed out after 7s"):
        client._run_codex("prompt", "", None)
