from __future__ import annotations

import pytest

from birkin import config
from birkin.profile_actions import ProfileActions
from birkin.profile_review import build_profile_review
from birkin.rolefiles import ProfileStore


def _actions(limits=None):
    return ProfileActions(ProfileStore(config.birkin_home(), limits or {}), approval_required=False)


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
