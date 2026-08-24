
from pathlib import Path

import pytest

from birkin import runtime
from birkin.llm import LLMClient
from birkin.skills.loader import Skill

USER = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


def test_local_cli_runs_configured_argv(monkeypatch):
    captured = {}

    # CLI runners go through _run_cli_capture (Popen + drain/poll for Esc-abort);
    # mock at that boundary -> (stdout, stderr, timed_out, aborted).
    def fake_capture(self, argv, prompt, abort=None):
        captured["cmd"] = argv
        captured["input"] = prompt
        return "hello from my-llm", "", False, False

    monkeypatch.setattr(LLMClient, "_run_cli_capture", fake_capture)
    c = LLMClient(provider="local-cli", model="", api_key="cli", base_url="",
                  cli_command=["my-llm", "--flag"])
    res = c.complete(system="SYS", messages=USER, tools=[])
    assert res["content"][0]["text"] == "hello from my-llm"
    assert "my-llm" in captured["cmd"] and "--flag" in captured["cmd"]
    # the flattened system + conversation is fed on stdin
    assert "SYS" in captured["input"] and "hi" in captured["input"]


def test_local_cli_without_command_returns_hint():
    c = LLMClient(provider="local-cli", model="", api_key="cli", base_url="",
                  cli_command=[])
    res = c.complete(system="s", messages=USER, tools=[])
    assert "No cli_command" in res["content"][0]["text"]


def test_dry_run_packet_api_provider_has_tools_and_no_call():
    cfg = {"provider": "anthropic", "model": "claude-sonnet-4-6", "max_depth": 2}
    pkt = runtime.build_dry_run_packet("find recent arxiv papers", cfg)
    assert pkt["provider"] == "anthropic"
    assert pkt["tools"]  # native tool-calling loop exposes tools
    assert "load_skill" in pkt["system"]
    assert pkt["usage"]["estTokens"] > 0
    assert pkt["user"] == "find recent arxiv papers"


def test_dry_run_packet_cli_provider_routes_skills():
    cfg = {"provider": "codex-cli", "model": ""}
    pkt = runtime.build_dry_run_packet(
        "find recent arxiv papers on transformer attention", cfg)
    assert pkt["tools"] == []          # CLI agents use their own tools
    assert "arxiv" in pkt["routed_skills"]


def test_dry_run_routes_the_same_office_skill_as_a_live_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an isolated CLI session and an Office DOCX request.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    cfg = {"provider": "codex-cli", "model": "", "harness_enabled": False}
    manager = runtime.build_manager(cfg)
    session = runtime.Session.__new__(runtime.Session)
    session.skills = manager
    live_skill_ids: list[str] = []

    def record_skill_id(skill: Skill) -> str:
        live_skill_ids.append(skill.name)
        return skill.name

    monkeypatch.setattr(manager, "render_skill", record_skill_id)

    # When: live and dry-run assemble routing for the same request.
    session._route_cli_skills("Create a Word DOCX contract summary")
    packet = runtime.build_dry_run_packet(
        "Create a Word DOCX contract summary", cfg,
    )

    # Then: both expose only the deterministic Word skill identifier.
    assert live_skill_ids == ["word-documents"]
    assert packet["routed_skills"] == live_skill_ids


def test_dry_run_packet_includes_neurosis_note_like_a_real_turn():
    # The dry-run system prompt must mirror an actual turn, which injects the
    # neurosis auto-trigger guidance. Check both provider branches.
    for prov, model in (("anthropic", "claude-sonnet-4-6"), ("codex-cli", "")):
        pkt = runtime.build_dry_run_packet(
            "plan a big vague project", {"provider": prov, "model": model,
                                         "neurosis_auto": True, "max_depth": 2})
        assert "when to run it automatically" in pkt["system"].lower()
