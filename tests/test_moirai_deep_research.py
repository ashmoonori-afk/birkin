"""The saturation-research pattern: does the loop actually converge?

The failure mode this guards is an EXPAND loop that never ends — a lead the
auditor rejected reappearing next wave because dedup only tracked followed
leads. That is the bug the upstream contract calls out by name, so it is the
thing to test rather than the prose.
"""

from __future__ import annotations

import json

import pytest

from birkin import moirai
from birkin.moirai import cli as moirai_cli


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


@pytest.fixture
def script():
    return moirai.load_script(moirai_cli.resolve_script_path("deep-research"))


def _spawn(script_replies):
    """Answer by label prefix, so a wave's shape drives the fake."""
    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        for key, value in script_replies.items():
            if key in prompt:
                return value if isinstance(value, str) else json.dumps(
                    value, ensure_ascii=False)
        return json.dumps({"findings": [], "leads": []}, ensure_ascii=False)
    return spawn


AXES = {"axes": [{"name": "a", "question": "qa"},
                 {"name": "b", "question": "qb"}]}


def test_the_pattern_loads_and_declares_its_roles(script):
    assert script.name == "deep-research"
    assert set(script.roles) == {"planner", "worker", "auditor"}
    assert script.roles["auditor"]["default"].startswith("codex:"), (
        "the auditor must be a different family from the worker")
    assert script.roles["worker"]["default"].startswith("claude:")


def test_a_question_is_required(script):
    out = moirai.run_script(script, cfg={}, args={}, spawn=_spawn({}))
    assert "error" in out["result"]


def test_a_failed_decomposition_stops_cleanly(script):
    out = moirai.run_script(script, cfg={}, args={"question": "q"},
                            spawn=_spawn({"겹치지 않는 조사 축": "not json"}))
    assert out["status"] == "completed"
    assert out["result"]["error"] == "축 분해 실패"


def test_findings_are_gathered_and_audited(script):
    replies = {
        "겹치지 않는 조사 축": AXES,
        "조사 축: a": {"findings": [{"claim": "A는 참", "basis": "근거A"}],
                       "leads": []},
        "조사 축: b": {"findings": [{"claim": "B는 참", "basis": "근거B"}],
                       "leads": []},
        "반증해": {"verdict": "corroborated", "reason": "독립 확인"},
        "이걸로 답을": "최종 답",
    }
    out = moirai.run_script(script, cfg={}, args={"question": "q"},
                            spawn=_spawn(replies))["result"]
    assert len(out["corroborated"]) == 2 and out["answer"] == "최종 답"
    assert out["unresolved"] == [] and out["refuted"] == []


def test_an_unresolved_verdict_is_not_promoted(script):
    replies = {
        "겹치지 않는 조사 축": AXES,
        "조사 축:": {"findings": [{"claim": "확실치 않음", "basis": "b"}],
                     "leads": []},
        "반증해": {"verdict": "unresolved", "reason": "확정 불가"},
        "이걸로 답을": "답",
    }
    out = moirai.run_script(script, cfg={}, args={"question": "q"},
                            spawn=_spawn(replies))["result"]
    assert out["corroborated"] == [] and len(out["unresolved"]) == 2


def test_a_repeated_lead_never_reopens_the_loop(script):
    """The convergence bug: dedup must cover every lead ever seen."""
    calls = []

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        if "겹치지 않는 조사 축" in prompt:
            return json.dumps({"axes": [{"name": "a", "question": "qa"}]})
        if "반증해" in prompt:
            return json.dumps({"verdict": "unresolved", "reason": "r"})
        if "이걸로 답을" in prompt:
            return "답"
        calls.append(prompt)
        # every worker keeps returning the SAME lead
        return json.dumps({"findings": [{"claim": "c", "basis": "b"}],
                           "leads": ["같은 리드"]}, ensure_ascii=False)

    out = moirai.run_script(script, cfg={}, args={"question": "q"},
                            spawn=spawn)
    assert out["status"] == "completed"
    # wave 1 axis + wave 2 follows the lead once; wave 3 finds nothing new
    assert len(calls) <= 3, f"the loop kept re-following one lead: {len(calls)}"
    assert out["result"]["leads_seen"] == 1


def test_the_loop_stops_after_consecutive_dry_waves(script):
    from birkin.moirai.patterns import deep_research

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        if "겹치지 않는 조사 축" in prompt:
            return json.dumps({"axes": [{"name": "a", "question": "qa"}]})
        if "반증해" in prompt:
            return json.dumps({"verdict": "corroborated", "reason": "r"})
        if "이걸로 답을" in prompt:
            return "답"
        return json.dumps({"findings": [{"claim": "c", "basis": "b"}],
                           "leads": []})

    out = moirai.run_script(script, cfg={}, args={"question": "q"},
                            spawn=spawn)["result"]
    assert out["waves"] <= deep_research.MAX_WAVES


def test_a_dead_worker_does_not_take_down_the_run(script):
    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        if "겹치지 않는 조사 축" in prompt:
            return json.dumps(AXES)
        if "조사 축: a" in prompt:
            raise RuntimeError("provider died")
        if "조사 축: b" in prompt:
            return json.dumps({"findings": [{"claim": "살아남음",
                                             "basis": "b"}], "leads": []})
        if "반증해" in prompt:
            return json.dumps({"verdict": "corroborated", "reason": "r"})
        return "답"

    out = moirai.run_script(script, cfg={}, args={"question": "q"},
                            spawn=spawn)
    assert out["status"] == "completed"
    assert len(out["result"]["corroborated"]) == 1


def test_the_pattern_is_listed_and_resolvable_by_name():
    assert moirai_cli.resolve_script_path("deep-research").is_file()
    assert moirai_cli.resolve_script_path("deep_research").is_file()


def test_it_credits_where_the_algorithm_came_from():
    import pathlib
    src = pathlib.Path(
        moirai_cli.resolve_script_path("deep-research")).read_text(
            encoding="utf-8")
    assert "oh-my-openagent" in src and "ulw-research" in src
