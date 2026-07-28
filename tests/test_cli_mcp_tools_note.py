"""CLI backends CAN call birkin's tools — the prompt has to say so.

birkin attaches its own MCP server to the codex child (llm.py `_run_codex`
appends `mcp_servers.birkin.*` whenever `birkin_mcp` is set, and morpheus turns
it on for every nightly run). Twelve tools are exposed: memory search/read/
write/link/rezone, skills list/load/create/improve, and propose_action.

But codex 0.145 does not list MCP tools upfront — they surface through
`tool_search_tool`. Probed live with morpheus's exact flags:

    "list the tool names you can call right now"
        -> 20 codex built-ins, ZERO birkin tools
    "use tool_search_tool to look for memory_write_note / propose_action"
        -> memory_write_note, propose_action        (all three flag variants)

So the tools are reachable and the model cannot see them, and nothing in the
prompt mentions they exist. The observable cost, from this install's own runs:
morpheus recorded proposals=[] on 07-25, 07-26 and 07-27 while writing "이
환경에는 Birkin 메모리·제안 도구가 제공되지 않고", and a cron job whose whole
job is tracking a number reported "이전 실행 기록이 없어 증감 확인 불가" on
BOTH of its runs — it had memory_write_note the entire time.

prompts.build_cli_system's own docstring asserted the opposite ("Those backends
can't call birkin's tools"), which is where the belief was encoded.
"""

from __future__ import annotations

import types

import pytest

from birkin import mcp_server, prompts, promptgate


def test_the_note_is_absent_by_default():
    """No MCP attached — promising tools that are not there would be worse."""
    sysp = prompts.build_cli_system(memory_block="", preloaded=None)
    assert "tool_search_tool" not in sysp


def test_the_note_names_the_real_server():
    """Drift guard: the block must name the server llm.py actually registers."""
    block = prompts.cli_mcp_block()
    assert mcp_server._SERVER_NAME in block
    assert "tool_search_tool" in block, (
        "the whole point is telling the model the tools are not listed upfront")


def test_the_note_says_what_the_tools_are_for():
    block = prompts.cli_mcp_block()
    low = block.lower()
    for capability in ("memory", "skill", "propose"):
        assert capability in low, f"the model is not told about {capability}"


def test_compose_cli_carries_it_through_extra():
    sysp = promptgate.compose_cli({}, extra=prompts.cli_mcp_block())
    assert "tool_search_tool" in sysp


def test_build_cli_system_docstring_no_longer_lies():
    doc = prompts.build_cli_system.__doc__ or ""
    assert "can't call birkin's tools" not in doc, (
        "the docstring still encodes the belief that caused this")


# -- the runtime only promises the tools when they are actually attached ----

class _Session:
    """Minimal stand-in exercising Session._build_cli_system's MCP branch."""

    def __init__(self, birkin_mcp):
        self.client = types.SimpleNamespace(birkin_mcp=birkin_mcp)
        self.cfg = {}
        self.agent = types.SimpleNamespace(system="")
        self.memory = types.SimpleNamespace(render=lambda: "")
        self.skills = types.SimpleNamespace(index=lambda: "")

    def _route_cli_skills(self, text, loaded_skills=None):
        return []

    def build(self, text="hi"):
        from birkin.runtime import Session
        Session._build_cli_system(self, text)
        return self.agent.system


@pytest.mark.parametrize("attached,expected", [(True, True), (False, False)])
def test_runtime_promises_the_tools_only_when_attached(attached, expected):
    assert ("tool_search_tool" in _Session(attached).build("아무 요청")) is expected


def test_missing_attribute_is_treated_as_not_attached():
    """API providers have no birkin_mcp attribute at all."""
    s = _Session(False)
    s.client = types.SimpleNamespace()
    assert "tool_search_tool" not in s.build()


def test_the_mcp_server_really_exposes_what_the_note_claims():
    """If the server ever stops shipping these, the prompt becomes a lie."""
    import json
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "birkin", "mcp-serve"],
        input="\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05",
                                   "capabilities": {},
                                   "clientInfo": {"name": "t", "version": "1"}}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                        "params": {}}),
        ]) + "\n",
        capture_output=True, text=True, timeout=60)
    names = set()
    for line in proc.stdout.strip().splitlines():
        msg = json.loads(line)
        if msg.get("id") == 2:
            names = {t["name"] for t in msg["result"]["tools"]}
    assert {"memory_write_note", "memory_search", "propose_action"} <= names, (
        f"MCP server no longer exposes what the prompt promises: {sorted(names)}")


# -- and only when the calls can actually succeed ---------------------------

def test_morpheus_does_not_attach_mcp_it_cannot_call(monkeypatch, capsys):
    """ hardwires approval to "never", which CANCELS MCP calls:

        codex exec --sandbox read-only ... -c mcp_servers.birkin.enabled=true
        "call memory_search"  ->  "user cancelled MCP tool call"

    -a is not accepted by exec, and -c approval_policy= is ignored (the banner
    still reads approval: never). Only cli_access="full" (which sends
    --dangerously-bypass-approvals-and-sandbox) lets a call through, and that
    also grants shell. Attaching tools that will be cancelled costs a discovery
    round-trip and produces a run that saves nothing while sounding like it
    tried — so don't attach them, and say why once.
    """
    import inspect
    from birkin import morpheus
    src = inspect.getsource(morpheus)
    assert 'session.client.birkin_mcp = (access == "full")' in src, (
        "morpheus attaches MCP tools regardless of whether they are callable")
    assert "cancels every MCP call" in src, (
        "the run must explain why it can save nothing")
