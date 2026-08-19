"""Confidence scoring and tiering (thinking frameworks, item 2)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from birkin import approvals, confidence, goals, store
from birkin.confidence import Signals


# -- score -----------------------------------------------------------------

def test_zero_signals_score_a_perfect_one():
    assert confidence.score(Signals()) == 1.0


def test_score_is_monotone_in_every_signal():
    base = Signals()
    worse = [
        replace(base, tool_errors=1),
        replace(base, schema_retries=1),
        replace(base, steer_count=1),
        replace(base, unsupported_claims=1),
        replace(base, turns_over_budget=True),
        replace(base, tool_errors=3, schema_retries=2, steer_count=4,
                unsupported_claims=2, turns_over_budget=True),
    ]
    clean = confidence.score(base)
    for signals in worse:
        assert confidence.score(signals) < clean
    # And monotone within one signal: more errors never raise the score.
    scores = [confidence.score(Signals(tool_errors=n)) for n in range(6)]
    assert all(b <= a for a, b in zip(scores, scores[1:]))


def test_score_is_clamped_into_unit_interval():
    assert confidence.score(Signals(tool_errors=100, schema_retries=100,
                                    steer_count=100, unsupported_claims=100,
                                    turns_over_budget=True)) == 0.0
    assert 0.0 <= confidence.score(Signals(steer_count=1)) <= 1.0


def test_negative_counts_are_treated_as_zero():
    assert confidence.score(Signals(tool_errors=-3)) == 1.0


# -- tier ------------------------------------------------------------------

def test_tier_thresholds_at_defaults():
    assert confidence.tier(0.0) == "strict"
    assert confidence.tier(0.39) == "strict"
    assert confidence.tier(0.4) == "standard"
    assert confidence.tier(0.79) == "standard"
    assert confidence.tier(0.8) == "fast"
    assert confidence.tier(1.0) == "fast"


def test_zero_signal_default_sits_on_the_fast_boundary():
    # A clean turn is exactly 1.0, which is fast under the defaults; one
    # tool error lands on the 0.8 boundary (still fast), two drop below it.
    assert confidence.tier_for(Signals()) == "fast"
    assert confidence.tier_for(Signals(tool_errors=1)) == "fast"
    assert confidence.tier_for(Signals(tool_errors=2, steer_count=1)) == "standard"


def test_tier_config_overrides():
    cfg = {"confidence_strict_below": 0.9, "confidence_fast_above": 0.95}
    assert confidence.tier(0.85, cfg) == "strict"
    assert confidence.tier(0.92, cfg) == "standard"
    assert confidence.tier(0.96, cfg) == "fast"


def test_tier_inverted_or_broken_config_falls_back_to_defaults():
    inverted = {"confidence_strict_below": 0.9, "confidence_fast_above": 0.1}
    assert confidence.tier(0.5, inverted) == "standard"
    assert confidence.tier(0.1, inverted) == "strict"
    broken = {"confidence_strict_below": "low", "confidence_fast_above": None}
    assert confidence.tier(0.5, broken) == "standard"
    assert confidence.tier(None, {}) == "standard"


# -- goals wiring ----------------------------------------------------------

def test_run_gate_records_confidence_note_from_signals(monkeypatch):
    state = goals.set_goal("Tiered verifier", gate="python -m pytest")
    monkeypatch.setattr(approvals, "execute_action",
                        lambda *_args, **_kwargs: "[exit 0] 2 passed")

    updated = goals.run_gate(state, {"auto_approve": ["shell"]},
                             signals=Signals(tool_errors=3))

    assert updated.gate_last["ok"] is True
    note = updated.gate_last["confidence"]
    assert note["tier"] == "standard"
    assert note["score"] == pytest.approx(0.7)


def test_run_gate_without_signals_records_no_note(monkeypatch):
    state = goals.set_goal("Plain verifier", gate="python -m pytest")
    monkeypatch.setattr(approvals, "execute_action",
                        lambda *_args, **_kwargs: "[exit 0] 2 passed")

    updated = goals.run_gate(state, {"auto_approve": ["shell"]})

    assert "confidence" not in updated.gate_last


def test_fast_tier_skips_rerunning_an_already_passing_gate(monkeypatch):
    state = goals.set_goal("Fast finish", gate="python -m pytest")
    monkeypatch.setattr(approvals, "execute_action",
                        lambda *_args, **_kwargs: "[exit 0] 2 passed")
    passed = goals.run_gate(state, {"auto_approve": ["shell"]})
    assert passed.gate_last["ok"] is True

    monkeypatch.setattr(
        approvals, "execute_action",
        lambda *_args, **_kwargs: pytest.fail("fast tier re-ran the gate"))
    finished, outcome = goals.request_completion(
        passed, {"auto_approve": ["shell"]}, signals=Signals())

    assert outcome == "done"
    assert finished is not None and finished.status == "done"


def test_strict_tier_reruns_the_verifier_over_a_previous_pass(monkeypatch):
    state = goals.set_goal("Strict finish", gate="python -m pytest")
    monkeypatch.setattr(approvals, "execute_action",
                        lambda *_args, **_kwargs: "[exit 0] 2 passed")
    passed = goals.run_gate(state, {"auto_approve": ["shell"]})

    calls = []
    monkeypatch.setattr(
        approvals, "execute_action",
        lambda category, payload, cfg=None: (
            calls.append(payload) or "[exit 0] 2 passed"))
    shaky = Signals(tool_errors=4, unsupported_claims=2,
                    turns_over_budget=True)
    finished, outcome = goals.request_completion(
        passed, {"auto_approve": ["shell"]}, signals=shaky)

    assert confidence.tier_for(shaky, {"auto_approve": ["shell"]}) == "strict"
    assert len(calls) == 1                      # verifier re-ran
    assert outcome == "done"
    assert finished is not None and finished.status == "done"


def test_standard_tier_preserves_existing_completion_behavior(monkeypatch):
    state = goals.set_goal("Standard finish", gate="python -m pytest")

    queued, outcome = goals.request_completion(
        state, {"auto_approve": []}, signals=Signals(tool_errors=2))
    assert outcome == "queued"
    assert queued is not None and queued.status == "active"
    assert len(store.list_pending()) == 1

    monkeypatch.setattr(approvals, "execute_action",
                        lambda *_args, **_kwargs: "[exit 1] 1 failed")
    failed, outcome = goals.request_completion(
        goals.get_active(), {"auto_approve": ["shell"]},
        signals=Signals(tool_errors=2))
    assert outcome == "failed"
    assert failed is not None and failed.gate_last["ok"] is False
    assert goals.get_active() is not None


def test_fast_tier_never_skips_a_gate_that_has_not_run(monkeypatch):
    state = goals.set_goal("Unverified fast finish", gate="python -m pytest")
    calls = []
    monkeypatch.setattr(
        approvals, "execute_action",
        lambda category, payload, cfg=None: (
            calls.append(payload) or "[exit 0] 2 passed"))

    finished, outcome = goals.request_completion(
        state, {"auto_approve": ["shell"]}, signals=Signals())

    assert len(calls) == 1
    assert outcome == "done"
    assert finished is not None and finished.status == "done"


# -- moirai wiring ---------------------------------------------------------

def test_moirai_verify_outcomes_fold_into_run_signals(tmp_path):
    from birkin import moirai

    goals.set_goal("Verify workflow")
    p = tmp_path / "wf.py"
    p.write_text(
        "meta = {\"name\": \"verified\"}\n"
        "\n"
        "def main(m):\n"
        "    first = m.verify(\"exit 1\")\n"
        "    second = m.verify(\"exit 0\")\n"
        "    return [first, second]\n",
        encoding="utf-8")

    out = moirai.run_script(moirai.load_script(p),
                            cfg={"auto_approve": ["shell"]})

    first, second = out["result"]
    assert first["ok"] is False and second["ok"] is True
    # m.verify passes no signals, so the gate records no confidence note.
    assert "confidence" not in first and "confidence" not in second
