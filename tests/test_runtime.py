"""Offline tests for the runtime session: ConfigError, run-record write, and
the CLI-provider system-prompt builder."""

from __future__ import annotations

import json
import threading
import time

import pytest

from birkin import config, curator, selfimprove, store
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


def test_build_cli_system_records_routed_skill_usage():
    s = build_session({"provider": "codex-cli", "model": ""})
    s._build_cli_system("find recent arxiv papers on transformer attention")
    assert curator.load_usage()["arxiv"]["count"] == 1


def test_cli_turn_schedules_background_skill_review_at_interval(monkeypatch):
    calls = []

    class _InlineThread:
        def __init__(self, *, target, daemon=False, **_kwargs):
            self.target = target

        def start(self):
            self.target()

        def is_alive(self):
            return False

    monkeypatch.setattr("birkin.runtime.threading.Thread", _InlineThread)
    monkeypatch.setattr(
        selfimprove,
        "review_cli_turn",
        lambda _ctx, transcript: calls.append(transcript) or "nothing new",
    )
    s = build_session({"provider": "claude-cli", "model": "",
                       "self_improve": True, "skill_nudge_interval": 2})
    s._record_turn("first task", "first reply")
    assert calls == []
    s._record_turn("second task", "second reply")
    assert calls == ["USER:\nsecond task\n\nASSISTANT:\nsecond reply"]


def test_cli_turn_starts_only_one_concurrent_skill_review(monkeypatch):
    created = []

    class _SlowThread:
        def __init__(self, *, target, **_kwargs):
            time.sleep(0.05)
            created.append(target)

        def start(self):
            pass

        def is_alive(self):
            return True

    real_thread = threading.Thread
    monkeypatch.setattr("birkin.runtime.threading.Thread", _SlowThread)
    s = build_session({"provider": "claude-cli", "model": "",
                       "self_improve": True, "skill_nudge_interval": 1})
    gate = threading.Barrier(3)

    def schedule():
        gate.wait()
        s._schedule_skill_review("task", "reply")

    workers = [real_thread(target=schedule) for _ in range(2)]
    for worker in workers:
        worker.start()
    gate.wait()
    for worker in workers:
        worker.join()

    assert len(created) == 1


def test_local_cli_does_not_run_unsandboxed_skill_review():
    s = build_session({"provider": "local-cli", "model": "",
                       "self_improve": True, "skill_nudge_interval": 1,
                       "cli_command": ["custom-agent"]})
    s._schedule_skill_review("task", "reply")
    assert s._skill_review_thread is None


def test_codex_cli_does_not_run_tool_capable_skill_review():
    s = build_session({"provider": "codex-cli", "model": "",
                       "self_improve": True, "skill_nudge_interval": 1})
    s._schedule_skill_review("task", "reply")
    assert s._skill_review_thread is None


def test_skill_review_thread_start_failure_does_not_break_turn(monkeypatch):
    class _BrokenThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("thread unavailable")

        def is_alive(self):
            return False

    monkeypatch.setattr("birkin.runtime.threading.Thread", _BrokenThread)
    s = build_session({"provider": "claude-cli", "model": "",
                       "self_improve": True, "skill_nudge_interval": 1})
    s._record_turn("task", "successful reply")
    assert s._skill_review_thread is None


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
