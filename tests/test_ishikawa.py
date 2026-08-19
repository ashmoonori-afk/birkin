"""Ishikawa debugging nudge (thinking-frameworks design, Item 6).

The nudge exists to stop a fix loop from narrowing to one cause category when
the same tool keeps failing. These tests pin the trigger (>= 2 failures
sharing a tool), the fixed category list the prompt must force hypotheses
across, the ASCII-only constraint, and the fail-open/disabled behavior.
"""

from __future__ import annotations

from birkin import ishikawa, promptgate


def _fail(label=None, role=None, phase=None, error="boom"):
    return {"label": label, "role": role, "phase": phase, "error": error,
            "status": "error"}


# ---------------- trigger --------------------------------------------------

def test_two_failures_sharing_a_tool_trigger_the_note():
    failures = [_fail(label="step-1"), _fail(label="step-1")]
    assert ishikawa.ishikawa_note(failures)


def test_one_failure_per_tool_does_not_trigger():
    failures = [_fail(label="step-1"), _fail(label="step-2")]
    assert ishikawa.ishikawa_note(failures) == ""


def test_empty_and_missing_failures_do_not_trigger(monkeypatch):
    assert ishikawa.ishikawa_note([]) == ""
    from birkin.moirai import journal
    monkeypatch.setattr(journal, "recent_failed_calls", lambda limit=10: [])
    assert ishikawa.ishikawa_note() == ""


def test_role_and_phase_fallback_identify_the_tool():
    assert ishikawa.shared_tool([_fail(role="worker"),
                                 _fail(role="worker")]) == "worker"
    assert ishikawa.shared_tool([_fail(phase="build"),
                                 _fail(phase="build")]) == "build"


def test_failures_without_any_tool_identity_count_toward_nothing():
    assert ishikawa.ishikawa_note([_fail(), _fail()]) == ""


# ---------------- content --------------------------------------------------

def test_note_lists_every_fishbone_category():
    note = ishikawa.ishikawa_note([_fail(label="deploy"), _fail(label="deploy")])
    for category in ishikawa.CATEGORIES:
        assert category in note
    assert "ISHIKAWA" in note
    assert "deploy" in note


def test_note_is_ascii_only():
    note = ishikawa.ishikawa_note([_fail(label="deploy"), _fail(label="deploy")])
    assert note.encode("ascii").decode("ascii") == note


# ---------------- promptgate hook ------------------------------------------

def test_turn_context_carries_the_note_when_enabled(monkeypatch):
    monkeypatch.setattr(ishikawa, "ishikawa_note",
                        lambda: ishikawa.render_note("step-9"))
    out = promptgate.compose_turn_context(
        {"session_id": "ishi-on", "ishikawa_enabled": True})
    assert "ISHIKAWA" in out and "step-9" in out


def test_turn_context_skips_the_note_when_disabled(monkeypatch):
    monkeypatch.setattr(ishikawa, "ishikawa_note",
                        lambda: ishikawa.render_note("step-9"))
    out = promptgate.compose_turn_context(
        {"session_id": "ishi-off", "ishikawa_enabled": False})
    assert "ISHIKAWA" not in out


def test_turn_context_survives_an_ishikawa_error(monkeypatch):
    def boom():
        raise RuntimeError("journal exploded")
    monkeypatch.setattr(ishikawa, "ishikawa_note", boom)
    # fail-open: the turn context still composes
    assert "ISHIKAWA" not in promptgate.compose_turn_context(
        {"session_id": "ishi-boom"})
