"""Thinking-framework sentinels (design Items 7 + 8).

Item 7: cross_examine's critic must attack along inversion and second-order
axes as *schema-required* keys (the report always has both), and the harness
refiner's proposal prompt must demand a failure mode and a long-term cost.

Item 8: the Minto pyramid — the main/CLI system prompts carry the
CONCLUSION-FIRST marker behind ``minto_enabled``, and the hard_task report
renders its VERDICT line first.

The assertions here pin machine-consumed sentinels (schema keys, marker
tokens, report line order), never prose.
"""

from __future__ import annotations

import json

import pytest

from birkin import harness_review, moirai, promptgate
from birkin.moirai import schema as S
from birkin.moirai.patterns import cross_examine


# ---------------- Item 7: cross_examine ------------------------------------

def test_critic_schema_requires_inversion_and_second_order():
    required = set(cross_examine.CRITIQUE_SCHEMA["required"])
    assert {"attack", "inversion", "second_order"} <= required


def test_a_critique_missing_inversion_is_rejected():
    with pytest.raises(S.SchemaError):
        S.validate({"attack": "a", "second_order": "s"},
                   cross_examine.CRITIQUE_SCHEMA)


def test_a_critique_missing_second_order_is_rejected():
    with pytest.raises(S.SchemaError):
        S.validate({"attack": "a", "inversion": "i"},
                   cross_examine.CRITIQUE_SCHEMA)


def test_a_full_critique_validates():
    S.validate({"attack": "a", "inversion": "i", "second_order": "s"},
               cross_examine.CRITIQUE_SCHEMA)


def test_critique_render_keeps_the_section_tokens():
    # the machine-consumed check is the schema above; the render keeps the
    # INVERSION/SECOND-ORDER tokens in the joined report
    rendered = cross_examine._render(
        {"attack": "a", "inversion": "i", "second_order": "s"})
    assert "INVERSION: i" in rendered
    assert "SECOND-ORDER: s" in rendered


def test_cross_examine_run_keeps_both_keys_in_the_report(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    answers = {
        "draft": "주장 초안",
        "revise": "수정된 최종 주장",
    }

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        label = opts.get("label") or ""
        if label in answers:
            return answers[label]
        return json.dumps({"attack": "틀린 곳", "inversion": "실패하는 모습",
                           "second_order": "3개월 뒤 비용"},
                          ensure_ascii=False)

    out = moirai.run_script(moirai.load_script(_pattern_path()),
                            cfg={}, spawn=spawn)
    assert out["status"] == "completed"
    critiques = out["result"]["critiques"]
    assert len(critiques) == 3
    for critique in critiques:
        assert {"attack", "inversion", "second_order"} <= set(critique)


def _pattern_path():
    from pathlib import Path
    return Path(cross_examine.__file__)


# ---------------- Item 7: harness_review proposal prompt --------------------

def test_proposal_prompt_demands_inversion_and_second_order():
    assert "INVERSION" in harness_review._PROPOSAL_SYSTEM
    assert "SECOND-ORDER" in harness_review._PROPOSAL_SYSTEM


# ---------------- Item 8: Minto pyramid ------------------------------------

def test_minto_marker_reaches_main_and_cli_prompts():
    cfg = {"neurosis_auto": False, "minto_enabled": True}
    assert "CONCLUSION-FIRST" in promptgate.compose_main(cfg, persona_text="")
    assert "CONCLUSION-FIRST" in promptgate.compose_cli(cfg, persona_text="")


def test_minto_marker_absent_when_disabled():
    cfg = {"neurosis_auto": False, "minto_enabled": False}
    assert "CONCLUSION-FIRST" not in promptgate.compose_main(cfg,
                                                             persona_text="")
    assert "CONCLUSION-FIRST" not in promptgate.compose_cli(cfg,
                                                            persona_text="")


def test_hard_task_report_renders_verdict_first(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin.moirai.patterns import hard_task
    replies = {
        "plan": json.dumps({"items": ["정리"]}),
        "decompose-1": json.dumps({"items": ["정리 A", "정리 B"]}),
        "step-1": json.dumps({"result": "A 끝", "followups": []}),
        "step-2": json.dumps({"result": "B 끝", "followups": []}),
    }

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        return replies[opts.get("label") or ""]

    out = moirai.run_script(moirai.load_script(hard_task.__file__),
                            args={"task": "청소"}, cfg={}, spawn=spawn)
    assert out["status"] == "completed"
    report = out["result"]
    assert isinstance(report, str) and report.splitlines()[0].startswith(
        "VERDICT: ")
    # verdict precedes the per-step evidence (one worker step ran)
    assert report.index("VERDICT:") < report.index("[1/1]")
