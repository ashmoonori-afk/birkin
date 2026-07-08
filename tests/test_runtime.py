"""Offline tests for the runtime session: ConfigError, run-record write, and
the CLI-provider system-prompt builder."""

from __future__ import annotations

import json

import pytest

from birkin import config, store
from birkin.runtime import ConfigError, build_session


def test_build_session_without_key_raises():
    cfg = {"provider": "anthropic", "model": "claude-sonnet-4-6"}
    # autouse fixture scrubs ANTHROPIC_API_KEY and cfg has no api_key
    with pytest.raises(ConfigError):
        build_session(cfg)


def test_build_session_with_cli_provider_no_key_succeeds():
    cfg = {"provider": "codex-cli", "model": ""}
    s = build_session(cfg)
    assert s.client.provider == "codex-cli"
    assert s.agent is not None
    assert s.skills is not None
    assert s.memory is not None


def test_record_turn_writes_run_and_ledger():
    s = build_session({"provider": "codex-cli", "model": ""})
    s._record_turn("hello there", "hi back\nsecond line")
    runs = store.list_runs()
    assert any(r["kind"] == "chat" for r in runs)
    r = [r for r in runs if r["kind"] == "chat"][0]
    assert r["details"]["provider"] == "codex-cli"
    assert r["summary"].startswith("hi back")
    assert r["usage"]["estTokens"] > 0
    lines = config.ledger_path().read_text(encoding="utf-8").splitlines()
    ledger = [json.loads(l) for l in lines if l.strip()]
    assert any(e["kind"] == "chat" for e in ledger)


def test_build_cli_system_injects_identity_memory_and_routed_skills():
    cfg = {"provider": "codex-cli", "model": ""}
    s = build_session(cfg)
    s.memory.write_note("User", "Prefers short answers.", note_type="preference")
    s._build_cli_system("find recent arxiv papers on transformer attention")
    sysp = s.agent.system
    assert "You are birkin" in sysp                    # identity
    assert "short answers" in sysp                     # memory injected
    assert "Skill: arxiv" in sysp                      # router picked arxiv
    # The CLI prompt must NOT include the agent's tool-loop guidance.
    assert "load_skill" not in sysp


def test_ask_skips_when_skills_unchanged_then_picks_up_new_skill(tmp_path):
    """reload_if_changed runs before each ask; adding a SKILL.md mid-session lands."""
    s = build_session({"provider": "codex-cli", "model": ""})
    n0 = len(s.skills.skills)
    new_dir = config.user_skills_dir() / "live-added"
    new_dir.mkdir()
    (new_dir / "SKILL.md").write_text(
        "---\nname: live-added\ndescription: x\n---\nbody\n", encoding="utf-8")
    s.skills.reload_if_changed(debounce=0.0)
    assert len(s.skills.skills) == n0 + 1
    assert s.skills.get("live-added") is not None
