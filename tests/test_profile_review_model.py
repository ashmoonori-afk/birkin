from __future__ import annotations

import pytest

from birkin import config
from birkin.profile_actions import ProfileActions
from birkin.profile_review import build_profile_review
from birkin.rolefiles import ProfileStore


class _FakeSkills:
    revision = 0

    def index(self) -> str:
        return ""

    def reload_if_changed(self, debounce=None) -> None:
        pass

    def route(self, text: str, limit: int = 3):
        return []

    def tools(self):
        return []


class _FakeAgent:
    def __init__(self, **kwargs):
        self.system = kwargs.get("system", "")
        self.registry = kwargs.get("registry")
        self.model = kwargs.get("model")
        self.last_tools = []
        self.last_iterations = 1

    def run(self, text: str, **kwargs) -> str:
        return "assistant reply"

    def reset(self) -> None:
        pass

    def steer(self, text: str) -> bool:
        return False


def _actions(limits=None):
    return ProfileActions(ProfileStore(config.birkin_home(), limits or {}), approval_required=False)


def test_runtime_constructs_review_service_and_records_configured_exchange(monkeypatch):
    from birkin import runtime

    completions: list[str] = []

    class FakeClient:
        def __init__(self, provider: str) -> None:
            self.provider = provider
            self.model = provider

        def complete(self, **kwargs):
            completions.append(kwargs["messages"][0]["content"][0]["text"])
            return {"content": [{"type": "text", "text": '{"profiles": {"preferences": "tone: concise"}}'}]}

    monkeypatch.setattr(runtime.config, "get_api_key", lambda cfg: "key")
    monkeypatch.setattr(runtime, "build_client", lambda cfg, api_key: FakeClient(str(cfg["provider"])))
    monkeypatch.setattr(runtime, "build_manager", lambda cfg: _FakeSkills())
    monkeypatch.setattr(runtime, "Agent", _FakeAgent)
    cfg = {
        **config.DEFAULT_CONFIG,
        "provider": "main",
        "model": "main-model",
        "checkpoints": False,
        "self_improve": False,
        "harness_enabled": False,
        "profile": {
            **config.DEFAULT_CONFIG["profile"],
            "enabled": True,
            "background_review": {"enabled": True, "provider": "aux", "model": "cheap", "digest_recent_turns": 1},
        },
    }

    session = runtime.build_session(cfg)
    assert session.profile_review_service is not None
    assert session.ask("user text", review_skills=False) == "assistant reply"
    session.profile_review_service.flush()

    entries = ProfileStore(config.birkin_home(), {}).snapshot().documents["preferences"].entries
    assert entries == ("tone: concise",)
    assert completions and "user text" in completions[-1] and "assistant reply" in completions[-1]


def test_runtime_does_not_construct_review_without_auxiliary_model(monkeypatch):
    from birkin import runtime

    main_complete_calls: list[str] = []

    class FakeClient:
        model = "main-model"

        def complete(self, **kwargs):
            main_complete_calls.append("called")
            return {"content": []}

    monkeypatch.setattr(runtime.config, "get_api_key", lambda cfg: "key")
    monkeypatch.setattr(runtime, "build_client", lambda cfg, api_key: FakeClient())
    monkeypatch.setattr(runtime, "build_manager", lambda cfg: _FakeSkills())
    monkeypatch.setattr(runtime, "Agent", _FakeAgent)
    cfg = {
        **config.DEFAULT_CONFIG,
        "provider": "main",
        "model": "main-model",
        "checkpoints": False,
        "self_improve": False,
        "harness_enabled": False,
        "profile": {
            **config.DEFAULT_CONFIG["profile"],
            "enabled": True,
            "background_review": {"enabled": True, "provider": "aux", "model": None, "digest_recent_turns": 1},
        },
    }

    session = runtime.build_session(cfg)
    assert session.profile_review_service is None
    assert session.ask("user text", review_skills=False) == "assistant reply"
    assert main_complete_calls == []
    assert ProfileStore(config.birkin_home(), {}).snapshot().documents["preferences"].entries == ()


def test_missing_auxiliary_provider_or_model_disables_review_and_never_calls_main_model():
    called = []
    cfg = {"profile": {"background_review": {"enabled": True, "provider": None, "model": None}}}
    service = build_profile_review(cfg, _actions(), lambda prompt: called.append(prompt) or "{}")
    assert service is None
    assert called == []


def test_digest_retains_exactly_configured_recent_turns_verbatim():
    prompts = []
    service = build_profile_review(
        {"profile": {"background_review": {"enabled": True, "provider": "aux", "model": "cheap", "digest_recent_turns": 2}}},
        _actions(),
        lambda prompt: prompts.append(prompt) or '{"profiles": {}}',
    )
    assert service is not None
    for i in range(4):
        fut = service.record_exchange(f"user-{i}", f"assistant-{i}", trusted=True, session_id="s")
        assert fut is not None
        fut.result(timeout=2)
    service.close()
    digest = prompts[-1]
    assert "user-0" not in digest and "assistant-0" not in digest
    assert "user-1" not in digest and "assistant-1" not in digest
    assert "user-2" in digest and "assistant-2" in digest
    assert "user-3" in digest and "assistant-3" in digest


def test_untrusted_exchange_is_not_recorded():
    prompts = []
    service = build_profile_review(
        {"profile": {"background_review": {"enabled": True, "provider": "aux", "model": "cheap", "digest_recent_turns": 1}}},
        _actions(),
        lambda prompt: prompts.append(prompt) or '{"profiles": {}}',
    )
    assert service is not None
    assert service.record_exchange("u", "a", trusted=False, session_id="s") is None
    service.flush()
    service.close()
    assert prompts == []


def test_reviewer_exception_does_not_raise_on_future_flush_or_close():
    service = build_profile_review(
        {"profile": {"background_review": {"enabled": True, "provider": "aux", "model": "cheap", "digest_recent_turns": 1}}},
        _actions(),
        lambda _prompt: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert service is not None
    fut = service.record_exchange("u", "a", trusted=True, session_id="s")
    assert fut is not None
    fut.result(timeout=2)
    service.flush()
    service.close()
    assert any("boom" in notice for notice in service.drain_notices("s") + service.drain_notices("default"))


def test_overflow_gets_one_repair_attempt_then_becomes_pending():
    calls = []
    responses = [
        '{"profiles": {"preferences": "this proposal is too long"}}',
        '{"profiles": {"preferences": "still far too long"}}',
    ]

    def complete(prompt: str) -> str:
        calls.append(prompt)
        return responses[len(calls) - 1]

    actions = _actions({"preferences": 8})
    service = build_profile_review(
        {"profile": {"background_review": {"enabled": True, "provider": "aux", "model": "cheap", "digest_recent_turns": 1}}},
        actions,
        complete,
    )
    assert service is not None
    fut = service.record_exchange("u", "a", trusted=True, session_id="s")
    assert fut is not None
    fut.result(timeout=2)
    service.close()
    assert len(calls) == 2
    assert len(actions.pending()) == 1
