"""Shell lifecycle hooks: consent, blocking, observing, injecting."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from birkin import hooks, store
from birkin.agent import Agent
from birkin.tools import ToolContext, ToolRegistry, Tool, ToolResult


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("BIRKIN_ACCEPT_HOOKS", raising=False)
    yield


@pytest.fixture
def script(tmp_path):
    """Make a real hook script and return the command that runs it."""
    def make(body: str, name: str = "hook.py") -> str:
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        return f'"{sys.executable}" "{path}"'
    return make


ECHO_BLOCK = """
import json, sys
payload = json.load(sys.stdin)
if "prod" in json.dumps(payload.get("tool_input", {})):
    print(json.dumps({"decision": "block",
                      "reason": "prod config is off limits"}))
"""

RECORD = """
import json, sys, pathlib
payload = json.load(sys.stdin)
log = pathlib.Path(sys.argv[0]).parent / "calls.log"
with log.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(payload) + "\\n")
"""

CONTEXT = """
import json, sys
print(json.dumps({"context": "On-call today: Dana."}))
"""


# -- config parsing --------------------------------------------------------

def test_parse_hooks_shapes():
    specs = hooks.parse_hooks({"hooks": {
        "pre_tool_call": [{"matcher": "run_shell", "command": "a", "timeout": 5}],
        "post_tool_call": ["b"],
    }})
    assert len(specs) == 2
    assert specs[0].matcher == "run_shell" and specs[0].timeout == 5
    assert specs[1].event == "post_tool_call" and specs[1].command == "b"


def test_unknown_events_and_junk_are_skipped(capsys):
    specs = hooks.parse_hooks({"hooks": {
        "on_banana": ["x"],
        "pre_tool_call": [{"command": ""}, 42, {"no_command": 1}, {"command": "ok"}],
    }})
    assert [s.command for s in specs] == ["ok"]
    assert "unknown hook event" in capsys.readouterr().out


def test_timeout_is_clamped():
    specs = hooks.parse_hooks({"hooks": {
        "pre_tool_call": [{"command": "a", "timeout": 99999},
                          {"command": "b", "timeout": "junk"},
                          {"command": "c", "timeout": 0}]}})
    assert [s.timeout for s in specs] == [hooks.MAX_TIMEOUT,
                                          hooks.DEFAULT_TIMEOUT, 1]


def test_matcher_selects_tools():
    spec = hooks.HookSpec("pre_tool_call", "cmd", matcher="run_shell|write_file")
    assert spec.matches("run_shell") and spec.matches("write_file")
    assert not spec.matches("read_file")
    assert hooks.HookSpec("pre_tool_call", "cmd").matches("anything")


def test_a_broken_matcher_regex_degrades_to_literal():
    spec = hooks.HookSpec("pre_tool_call", "cmd", matcher="[unclosed")
    assert spec.matches("[unclosed") and not spec.matches("read_file")


# -- consent ---------------------------------------------------------------

def _cfg(script_cmd, event="pre_tool_call", **kw):
    cfg = {"hooks": {event: [{"command": script_cmd}]}}
    cfg.update(kw)
    return cfg


def test_headless_without_optin_skips_hooks(script, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert hooks.build_bus(_cfg(script(ECHO_BLOCK))) is None
    assert "not approved, skipping" in capsys.readouterr().out


def test_env_optin_approves(script, monkeypatch):
    monkeypatch.setenv("BIRKIN_ACCEPT_HOOKS", "1")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert hooks.build_bus(_cfg(script(ECHO_BLOCK))) is not None


def test_config_optin_approves(script, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    bus = hooks.build_bus(_cfg(script(ECHO_BLOCK), hooks_auto_accept=True))
    assert bus is not None


def test_consent_is_remembered_across_runs(script, monkeypatch):
    cmd = script(ECHO_BLOCK)
    monkeypatch.setenv("BIRKIN_ACCEPT_HOOKS", "1")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert hooks.build_bus(_cfg(cmd)) is not None

    monkeypatch.delenv("BIRKIN_ACCEPT_HOOKS")
    assert hooks.build_bus(_cfg(cmd)) is not None, "allowlist should carry over"


def test_legacy_discrete_hook_consent_requires_managed_shell_reapproval(
    script,
) -> None:
    command = script(ECHO_BLOCK)
    store._write_json(
        hooks._allowlist_path(),
        [
            {
                "event": "pre_tool_call",
                "command": command,
                "approved_at": "2026-01-01T00:00:00",
            }
        ],
    )

    assert hooks.is_allowed(hooks.HookSpec("pre_tool_call", command)) is False


def test_tty_prompt_yes_and_no(script, monkeypatch):
    cmd = script(ECHO_BLOCK)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    assert hooks.build_bus(_cfg(cmd)) is None

    monkeypatch.setattr("builtins.input", lambda *_: "y")
    assert hooks.build_bus(_cfg(cmd)) is not None


def test_revoke_forgets_consent(script, monkeypatch):
    cmd = script(ECHO_BLOCK)
    monkeypatch.setenv("BIRKIN_ACCEPT_HOOKS", "1")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    hooks.build_bus(_cfg(cmd))
    assert hooks.revoke(cmd) == 1

    monkeypatch.delenv("BIRKIN_ACCEPT_HOOKS")
    assert hooks.build_bus(_cfg(cmd)) is None


def test_no_hooks_configured_is_the_zero_cost_path():
    assert hooks.build_bus({}) is None
    assert hooks.build_bus({"hooks": {}}) is None


# -- response parsing ------------------------------------------------------

def test_both_block_wire_shapes_are_accepted():
    claude = json.dumps({"decision": "block", "reason": "nope"})
    canonical = json.dumps({"action": "block", "message": "nope"})
    for text in (claude, canonical):
        assert hooks._parse_response(text) == {"action": "block", "message": "nope"}


def test_context_and_silence():
    assert hooks._parse_response('{"context": "hi"}') == {"context": "hi"}
    assert hooks._parse_response("") is None
    assert hooks._parse_response("not json") is None
    assert hooks._parse_response('{"unrelated": 1}') is None
    assert hooks._parse_response("[1,2]") is None


# -- execution -------------------------------------------------------------

def _bus(cfg, monkeypatch):
    monkeypatch.setenv("BIRKIN_ACCEPT_HOOKS", "1")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    return hooks.build_bus(cfg)


def test_pre_tool_hook_blocks(script, monkeypatch):
    bus = _bus(_cfg(script(ECHO_BLOCK)), monkeypatch)
    assert bus.pre_tool("write_file", {"path": "prod.yaml"}) \
        == "prod config is off limits"
    assert bus.pre_tool("write_file", {"path": "dev.yaml"}) is None


def test_pre_llm_hook_returns_context(script, monkeypatch):
    bus = _bus(_cfg(script(CONTEXT), event="pre_llm_call"), monkeypatch)
    assert bus.pre_llm("hello") == "On-call today: Dana."


def test_post_tool_hook_receives_the_result(script, tmp_path, monkeypatch):
    bus = _bus(_cfg(script(RECORD), event="post_tool_call"), monkeypatch)
    bus.post_tool("run_shell", {"command": "ls"}, "output here", False)
    logged = json.loads((tmp_path / "calls.log").read_text(encoding="utf-8"))
    assert logged["hook_event_name"] == "post_tool_call"
    assert logged["tool_name"] == "run_shell"
    assert logged["extra"]["content"] == "output here"


def test_payload_matches_the_documented_wire_format(script, tmp_path, monkeypatch):
    bus = _bus(_cfg(script(RECORD)), monkeypatch)
    bus.pre_tool("read_file", {"path": "a.py"})
    logged = json.loads((tmp_path / "calls.log").read_text(encoding="utf-8"))
    assert set(logged) >= {"hook_event_name", "tool_name", "tool_input",
                           "session_id", "cwd"}


def test_a_failing_hook_does_not_block(script, monkeypatch):
    bus = _bus(_cfg(script("import sys; sys.exit(3)")), monkeypatch)
    assert bus.pre_tool("read_file", {}) is None, "fail open, not closed"


def test_a_missing_hook_command_does_not_block(monkeypatch, capsys):
    monkeypatch.setenv("BIRKIN_ACCEPT_HOOKS", "1")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    bus = hooks.build_bus(_cfg("definitely-not-a-real-command-xyz"))
    assert bus.pre_tool("read_file", {}) is None


def test_a_hanging_hook_times_out(script, monkeypatch):
    cmd = script("import time; time.sleep(30)")
    cfg = {"hooks": {"pre_tool_call": [{"command": cmd, "timeout": 1}]}}
    bus = _bus(cfg, monkeypatch)
    assert bus.pre_tool("read_file", {}) is None


def test_matcher_limits_which_calls_pay(script, tmp_path, monkeypatch):
    cmd = script(RECORD)
    cfg = {"hooks": {"pre_tool_call": [{"command": cmd, "matcher": "run_shell"}]}}
    bus = _bus(cfg, monkeypatch)
    bus.pre_tool("read_file", {})
    assert not (tmp_path / "calls.log").exists()
    bus.pre_tool("run_shell", {})
    assert (tmp_path / "calls.log").exists()


def test_injected_context_is_capped(script, monkeypatch):
    cmd = script('import json; print(json.dumps({"context": "x" * 50000}))')
    bus = _bus(_cfg(cmd, event="pre_llm_call"), monkeypatch)
    assert len(bus.pre_llm("hi")) == hooks.MAX_CONTEXT_CHARS


# -- integration -----------------------------------------------------------

def test_blocked_tool_never_runs_and_the_model_is_told(script, monkeypatch):
    bus = _bus(_cfg(script(ECHO_BLOCK)), monkeypatch)
    ran = []
    ctx = ToolContext(cfg={"spill_threshold": 0}, client=None, cwd=Path("."),
                      hooks=bus)
    reg = ToolRegistry(ctx)
    reg.register(Tool(name="write_file", description="d", input_schema={},
                      fn=lambda inp, c: ran.append(inp) or ToolResult("wrote")))

    blocked = reg.execute("write_file", {"path": "prod.yaml"})
    assert blocked.is_error and "off limits" in blocked.content
    assert ran == [], "the tool must not have run"

    allowed = reg.execute("write_file", {"path": "dev.yaml"})
    assert not allowed.is_error and len(ran) == 1


def test_post_tool_observes_real_registry_results(script, tmp_path, monkeypatch):
    bus = _bus(_cfg(script(RECORD), event="post_tool_call"), monkeypatch)
    ctx = ToolContext(cfg={"spill_threshold": 0}, client=None, cwd=Path("."),
                      hooks=bus)
    reg = ToolRegistry(ctx)
    reg.register(Tool(name="read_file", description="d", input_schema={},
                      fn=lambda inp, c: ToolResult("body")))
    reg.execute("read_file", {"path": "x"})
    logged = json.loads((tmp_path / "calls.log").read_text(encoding="utf-8"))
    assert logged["extra"]["content"] == "body"


def test_pre_llm_context_reaches_the_system_prompt(script, monkeypatch):
    bus = _bus(_cfg(script(CONTEXT), event="pre_llm_call"), monkeypatch)
    seen = {}

    class Client:
        provider = "anthropic"

        def complete(self, *, system, messages, **kw):
            seen["system"] = system
            return {"role": "assistant",
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn"}

    class Reg:
        def specs(self):
            return []

        def execute(self, *a):
            raise AssertionError

    Agent(client=Client(), system="base", registry=Reg(), hooks=bus,
          self_improve=False).run("who is on call?")
    assert "On-call today: Dana." in seen["system"]
    assert seen["system"].startswith("base")


def test_no_bus_means_no_overhead():
    ctx = ToolContext(cfg={"spill_threshold": 0}, client=None, cwd=Path("."))
    assert ctx.hooks is None
    reg = ToolRegistry(ctx)
    reg.register(Tool(name="t", description="d", input_schema={},
                      fn=lambda inp, c: ToolResult("fine")))
    assert reg.execute("t", {}).content == "fine"
