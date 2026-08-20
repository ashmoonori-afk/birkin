"""Warm profile sessions keep fixed prompt snapshots and notify staleness."""

from __future__ import annotations

from pathlib import Path

from birkin import config
from birkin.rolefiles import ProfileDocument, ProfileSnapshot


def _snapshot(revision: str, guidance: str) -> ProfileSnapshot:
    doc = ProfileDocument(
        name="preferences",
        guidance=guidance,
        entries=(guidance,),
        used=len(guidance),
        limit=1000,
        revision=revision + "-doc",
    )
    return ProfileSnapshot(documents={"preferences": doc}, revision=revision)


def _session(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import runtime

    cfg = {
        **config.DEFAULT_CONFIG,
        "provider": "claude-cli",
        "model": "haiku",
        "checkpoints": False,
        "repl_warm_session": True,
        "self_improve": False,
    }
    config.save_config(cfg)
    monkeypatch.setattr(runtime, "_profile_snapshot", lambda: _snapshot("rev-a", "INITIAL-PROFILE"))
    return runtime.build_session(cfg)


def test_warm_system_prompt_keeps_its_profile_snapshot(tmp_path, monkeypatch) -> None:
    from birkin import claude_session, runtime

    captured: dict[str, str] = {}

    class FakeClaudeSession:
        def __init__(self, **kwargs):
            captured["system"] = str(kwargs["append_system_prompt"])

        def close(self) -> None:
            pass

    current = {"snapshot": _snapshot("rev-a", "INITIAL-PROFILE")}
    monkeypatch.setattr(runtime, "_profile_snapshot", lambda: current["snapshot"])
    monkeypatch.setattr(claude_session, "ClaudeStreamSession", FakeClaudeSession)

    s = _session(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "_profile_snapshot", lambda: current["snapshot"])
    _ = s._build_warm()
    current["snapshot"] = _snapshot("rev-b", "UPDATED-PROFILE")

    assert "INITIAL-PROFILE" in captured["system"]
    assert "UPDATED-PROFILE" not in captured["system"]


def test_revision_change_emits_once_per_unseen_revision(tmp_path, monkeypatch) -> None:
    from birkin import runtime

    s = _session(tmp_path, monkeypatch)

    class FakeWarm:
        def ask(self, text: str, on_text=None) -> str:
            return "reply"

    revisions = ["rev-a"]
    s._warm = FakeWarm()
    s._warm_profile_revision = "rev-a"
    monkeypatch.setattr(runtime, "_profile_revision", lambda: revisions[-1])
    notices: list[str] = []

    assert s._warm_ask("first", notices.append) == "reply"
    revisions.append("rev-b")
    assert s._warm_ask("second", notices.append) == "reply"
    assert s._warm_ask("third", notices.append) == "reply"
    revisions.append("rev-c")
    assert s._warm_ask("fourth", notices.append) == "reply"

    assert notices == [
        "profile updated - /new required",
        "profile updated - /new required",
    ]
    assert "profile updated - /new required" not in s.agent.system


def test_review_service_notices_are_drained_when_present(tmp_path, monkeypatch) -> None:
    from birkin import runtime

    s = _session(tmp_path, monkeypatch)

    class FakeWarm:
        def ask(self, text: str, on_text=None) -> str:
            return "reply"

    class ReviewService:
        def __init__(self) -> None:
            self.sessions: list[str] = []

        def drain_notices(self, session_id: str) -> tuple[str, ...]:
            self.sessions.append(session_id)
            return ("review notice",)

    s._warm = FakeWarm()
    s._warm_profile_revision = "rev-a"
    s.profile_review_service = ReviewService()
    monkeypatch.setattr(runtime, "_profile_revision", lambda: "rev-a")
    notices: list[str] = []

    s._warm_ask("hello", notices.append, session_id="session-x")

    assert notices == ["review notice"]
    assert s.profile_review_service.sessions == ["session-x"]
