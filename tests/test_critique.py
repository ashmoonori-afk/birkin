"""Hyperplan (v2 #6) — adversarial plan critique."""

from __future__ import annotations

from birkin import critique


def test_lenses_cycle_to_count():
    assert len(critique.lenses_for(3)) == 3
    assert len(critique.lenses_for(7)) == 7        # cycles past the 5 base lenses
    names = [n for n, _ in critique.lenses_for(2)]
    assert names == ["completeness", "ordering"]


def test_build_prompt_is_hostile_and_scoped():
    p = critique.build_prompt("1. do X\n2. do Y", "risk", "what is risky?")
    assert "[Hyperplan:risk]" in p and "do X" in p and "HOSTILE" in p


def test_critique_flags_findings_and_skips_ok():
    plan = "1. ship it"

    def ask(prompt):
        # critics: first finds an issue, rest say OK
        return "• no tests" if "completeness" in prompt else "OK"
    out = critique.critique(ask, plan, n=3)
    assert out["revise"] is True
    assert len(out["issues"]) == 1 and out["issues"][0]["lens"] == "completeness"


def test_critique_all_ok_means_no_revise():
    out = critique.critique(lambda p: "OK", "1. solid plan", n=3)
    assert out["revise"] is False and out["issues"] == []


def test_critique_skips_failing_critics():
    def ask(prompt):
        raise RuntimeError("critic crashed")
    out = critique.critique(ask, "plan", n=2)
    assert out["issues"] == [] and out["revise"] is False
