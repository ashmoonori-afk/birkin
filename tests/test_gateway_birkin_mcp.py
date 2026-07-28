"""The gateway had no birkin tools, so it could not remember anything.

Observed in production (Telegram, 2026-07-28): the user said "넌 앞으로 스스로를
Jane 이라고 부를거야. 기억해놓고 …" and birkin replied that it had no local
memory path and could not persist. It was telling the truth — two gaps stacked:

  1. On a CLI provider birkin's own tool registry is unreachable (the child
     runs its own tool loop; llm._cli_complete never returns tool_use), and
     nothing attached birkin's MCP server to the gateway's codex session.
     `grep birkin_mcp` found it set in morpheus.py and selfimprove.py only.
  2. Even with the server attached, every call was refused. Codex asks per
     tool call with an MCP *elicitation*, and _read_stdout answered EVERY
     server-initiated request with {"decision": "decline"} — no method check.
     Measured: "user rejected MCP tool call".

Captured live from codex 0.145 to get the shape right:

    method  mcpServer/elicitation/request
    params  {"serverName": "birkin", "mode": "form",
             "requestedSchema": {"type": "object", "properties": {}},
             "message": "Allow the birkin MCP server to run tool
                         \\"memory_search\\"?",
             "_meta": {"codex_approval_kind": "mcp_tool_call", ...}}

Replying {"action": "accept", "content": {}} let it through — verified
end to end against the real vault: "OK 8".

The carve-out is deliberately narrow. exec and apply_patch still decline, as
does any OTHER MCP server, and a session that did not attach birkin's server
declines even a birkin-shaped ask.
"""

from __future__ import annotations

import pytest

from birkin.codex_session import (_MCP_ELICITATION, CodexAppServerSession,
                                  _server_name)

DECLINE = {"decision": "decline"}
ACCEPT = {"action": "accept", "content": {}}


def _ask(server: str = "birkin", method: str = _MCP_ELICITATION) -> dict:
    return {"id": 7, "method": method, "params": {"serverName": server}}


# -- who gets approved -----------------------------------------------------

def test_birkin_tool_call_is_approved_when_attached():
    s = CodexAppServerSession(birkin_mcp=True)
    assert s._approval_result(_ask()) == ACCEPT


def test_other_mcp_servers_are_still_declined():
    """A company MCP server is not birkin's to auto-approve."""
    s = CodexAppServerSession(birkin_mcp=True)
    assert s._approval_result(_ask(server="notion")) == DECLINE


def test_exec_and_patch_approvals_are_still_declined():
    """The original guarantee: a headless gateway never approves a write it
    was asked to judge."""
    s = CodexAppServerSession(birkin_mcp=True)
    for method in ("execCommandApproval", "applyPatchApproval",
                   "item/approvalRequest"):
        assert s._approval_result(_ask(method=method)) == DECLINE


def test_a_session_without_mcp_declines_even_a_birkin_ask():
    """Only a session that deliberately attached the server answers for it."""
    s = CodexAppServerSession()
    assert s._approval_result(_ask()) == DECLINE


def test_a_missing_server_name_declines():
    s = CodexAppServerSession(birkin_mcp=True)
    assert s._approval_result({"id": 1, "method": _MCP_ELICITATION}) == DECLINE


def test_the_server_name_matches_the_one_actually_registered():
    """Drift guard: the name codex reports must be the name we register."""
    from birkin import mcp_server
    assert _server_name() == mcp_server._SERVER_NAME
    args = " ".join(mcp_server.codex_config_args(scope="full"))
    assert f"mcp_servers.{mcp_server._SERVER_NAME}." in args


# -- the server is only attached when asked for -----------------------------

def test_argv_carries_the_mcp_server_when_enabled():
    argv = CodexAppServerSession(model="gpt-5.6-luna", birkin_mcp=True)._build_argv()
    joined = " ".join(argv)
    assert "mcp_servers.birkin.command=" in joined
    assert "mcp_servers.birkin.enabled=true" in joined


def test_argv_is_unchanged_by_default():
    assert not any("mcp_servers" in a
                   for a in CodexAppServerSession(model="gpt-5.6-luna")._build_argv())


def test_sandbox_and_approval_flags_survive_the_addition():
    """The MCP args must not displace the security overrides that follow."""
    joined = " ".join(
        CodexAppServerSession(model="gpt-5.6-luna", birkin_mcp=True,
                              sandbox_mode="read-only")._build_argv())
    assert 'sandbox_mode="read-only"' in joined
    assert 'approval_policy="never"' in joined


# -- and the gateway asks for it -------------------------------------------

def test_gateway_attaches_birkin_mcp_to_its_codex_session():
    """Without this the gateway is a chat that cannot write to the vault —
    which is the product's headline feature."""
    import inspect

    from birkin.gateway import core
    src = inspect.getsource(core.Gateway)
    assert "birkin_mcp=True" in src, (
        "the gateway builds its codex session without birkin's tools")
