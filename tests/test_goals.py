from __future__ import annotations

import json

import pytest

from birkin import approvals, config, goals, store
from birkin.runtime import build_session


def test_set_goal_persists_complete_state_and_replaces_active_goal():
    first = goals.set_goal("Ship persisted session goals", budget=1000,
                           gate="python -m pytest")
    second = goals.set_goal("Document slash wiring")

    assert first.slug == "ship-persisted-session-goals"
    raw = json.loads((config.goals_dir() / f"{first.slug}.json").read_text(
        encoding="utf-8"))
    assert raw == {
        "slug": first.slug,
        "objective": "Ship persisted session goals",
        "budget_tokens": 1000,
        "tokens_used": 0,
        "status": "paused",
        "gate_cmd": "python -m pytest",
        "gate_last": None,
        "created_at": first.created_at,
        "updated_at": raw["updated_at"],
    }
    assert goals.get_active() == second


def test_set_goal_validates_objective_and_budget():
    with pytest.raises(ValueError, match="objective"):
        goals.set_goal("  ")
    for bad in (0, -1, True, "100"):
        with pytest.raises(ValueError, match="budget"):
            goals.set_goal("valid", budget=bad)


def test_usage_accumulates_and_pause_done_are_persisted():
    goals.set_goal("Count this turn", budget=10)
    assert goals.add_usage(3, 4).tokens_used == 7
    assert goals.add_usage(2, 3).tokens_used == 12
    assert "OVER" in goals.render_status()

    paused = goals.pause()
    assert paused is not None and paused.status == "paused"
    assert goals.get_active() is None
    assert goals.add_usage(100, 100) is None

    resumed = goals.set_goal("Finish this goal")
    finished = goals.done()
    assert finished is not None and finished.slug == resumed.slug
    assert finished.status == "done"
    assert goals.get_active() is None


def test_render_status_is_one_line_and_reports_budget_and_gate():
    goals.set_goal("A very long objective " * 8, budget=500,
                   gate="python -m pytest")
    rendered = goals.render_status()
    assert "\n" not in rendered
    assert len(rendered) < 140
    assert "0/500" in rendered
    assert "gate: pending" in rendered


def test_gate_is_queued_and_never_executed_without_shell_autoapproval(
        tmp_path, monkeypatch):
    marker = tmp_path / "must-not-exist"
    state = goals.set_goal("Approval gated", gate=f"echo bad > {marker}")
    monkeypatch.setattr(
        approvals, "execute_action",
        lambda *_args, **_kwargs: pytest.fail("gate executed directly"))

    updated = goals.run_gate(state, {"auto_approve": []})

    assert updated.gate_last is None
    assert not marker.exists()
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0]["category"] == "shell"
    assert pending[0]["payload"]["command"] == state.gate_cmd


def test_autoapproved_gate_uses_approval_executor_and_records_result(monkeypatch):
    state = goals.set_goal("Run verifier", gate="python -m pytest")
    calls = []
    monkeypatch.setattr(
        approvals, "execute_action",
        lambda category, payload, cfg=None: (
            calls.append((category, payload, cfg)) or "[exit 0] 2 passed"))

    updated = goals.run_gate(state, {"auto_approve": ["shell"]})

    assert calls == [("shell", {"command": "python -m pytest"},
                      {"auto_approve": ["shell"]})]
    assert updated.gate_last is not None
    assert updated.gate_last["ok"] is True
    assert updated.gate_last["output_tail"] == "[exit 0] 2 passed"
    assert updated.gate_last["at"]
    assert goals.get_active() == updated


def test_runtime_records_estimated_input_and_output_usage(monkeypatch):
    state = goals.set_goal("Account chat")
    session = build_session({"provider": "codex-cli", "model": "",
                             "self_improve": False,
                             "harness_enabled": False})

    session._record_turn("abcd", "abcdefgh", review_skills=False)

    updated = goals.get_active()
    expected = (store.estimate_usage(session.agent.system, "abcd")["estTokens"]
                + store.estimate_usage("abcdefgh")["estTokens"])
    assert updated is not None and updated.slug == state.slug
    assert updated.tokens_used == expected
