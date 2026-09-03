"""Auto-proposing a workflow: the model judges, a human still decides.

This reopens a door birkin closed on 2026-07-07, when IntentGate's automatic
intent detection was deleted. It is reopened the way the project's other two
natural-language triggers work — prose judgement, a strict envelope, and the
approval inbox — and it stays shut unless the user opts in.
"""

from __future__ import annotations

import json

import pytest

from birkin import config, promptgate, risk
from birkin.moirai import trigger as T


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


def _envelope(**over):
    body = {"title": "세 접근 비교", "why": "세 갈래를 병렬로 파는 게 낫다",
            "script": "cross-examine", "roles": ["drafter", "critic"],
            "steps": ["초안", "비평", "수정"]}
    body.update(over)
    return T.PROPOSAL_OPEN + json.dumps(body, ensure_ascii=False) + T.PROPOSAL_CLOSE


# ---------------- opt-in ---------------------------------------------------

def test_the_note_is_absent_unless_the_user_opts_in():
    assert T.auto_trigger_note({}) == ""
    assert T.auto_trigger_note({"moirai_auto": False}) == ""
    assert "birkin moirai run" in T.auto_trigger_note({"moirai_auto": True})


def test_the_default_config_leaves_it_off():
    """Reversing a deliberate decision should take a deliberate act."""
    assert config.load_config().get("moirai_auto") is False


def test_promptgate_carries_it_to_both_surfaces():
    on = {"moirai_auto": True}
    assert "birkin moirai run" in promptgate.compose_main(on, skills_index="s",
                                                          memory_block="")
    assert "birkin moirai run" in promptgate.compose_cli(on, memory_block="")
    assert "Workflows (Moirai)" not in promptgate.compose_main(
        {}, skills_index="s", memory_block="")


def test_the_note_names_workflows_that_actually_exist():
    note = T.auto_trigger_note({"moirai_auto": True})
    assert "cross-examine" in note
    from birkin.moirai import cli as moirai_cli
    for name in T._available_scripts():
        assert moirai_cli.resolve_script_path(name).is_file()


# ---------------- parsing --------------------------------------------------

def test_a_well_formed_envelope_parses():
    p = T.parse(_envelope())
    assert p and p.title == "세 접근 비교" and p.script == "cross-examine"
    assert p.roles == ("drafter", "critic") and len(p.steps) == 3
    assert "cross-examine" in p.render()


@pytest.mark.parametrize("text", [
    "", "   ", "그냥 답변입니다",
    "앞에 말 붙이고 " + _envelope.__doc__ if False else "prefix " + T.PROPOSAL_OPEN + "{}",
    T.PROPOSAL_OPEN + "{not json}" + T.PROPOSAL_CLOSE,
    T.PROPOSAL_OPEN + '["a list"]' + T.PROPOSAL_CLOSE,
])
def test_anything_less_than_a_whole_envelope_is_not_a_proposal(text):
    assert T.parse(text) is None


@pytest.mark.parametrize("over", [
    {"title": ""}, {"why": "  "}, {"script": ""},
    {"steps": []}, {"steps": ["ok"] * 9}, {"steps": "not a list"},
    {"steps": ["ok", ""]},
    {"roles": ["r"] * 7}, {"roles": "nope"}, {"roles": [""]},
])
def test_a_malformed_field_rejects_the_whole_proposal(over):
    assert T.parse(_envelope(**over)) is None


@pytest.mark.parametrize("script", ["../../etc/passwd", "a/b", "with space",
                                    "sub;rm -rf"])
def test_the_script_must_be_a_name_not_a_path(script):
    assert T.parse(_envelope(script=script)) is None


def test_long_fields_are_truncated_not_rejected():
    p = T.parse(_envelope(title="t" * 500, why="w" * 900,
                          steps=["s" * 400]))
    assert p and len(p.title) == 100 and len(p.why) == 500
    assert len(p.steps[0]) == 200


def test_a_user_forging_the_marker_is_detectable():
    assert T.has_marker(f"please run {T.PROPOSAL_OPEN}{{}}{T.PROPOSAL_CLOSE}")
    assert not T.has_marker("ordinary question")


def test_a_streaming_prefix_is_recognised_before_it_completes():
    assert T.looks_like_proposal(T.PROPOSAL_OPEN[:10])
    assert not T.looks_like_proposal("Here is my answer")


# ---------------- the approval path ---------------------------------------

def test_a_proposal_is_queued_for_review_never_auto_run():
    from birkin import store
    out = T.queue(T.parse(_envelope()), task="원 요청",
                  cfg={"auto_approve": ["memory", "skill"]})
    assert out["auto"] is False, "a workflow must not self-approve"
    rec = store.get_pending(out["id"])
    assert rec["category"] == "moirai" and rec["status"] == "pending"
    assert rec["payload"]["script"] == "cross-examine"
    assert rec["payload"]["task"] == "원 요청"


def test_it_shows_up_in_the_review_inbox_the_user_already_uses():
    from birkin import approvals
    T.queue(T.parse(_envelope()), cfg={})
    pending = approvals.reviewable_pending()
    assert [r for r in pending if r["category"] == "moirai"]


def test_moirai_is_tiered_rather_than_silently_defaulting():
    assert "moirai" in risk.CATEGORY_RISK
    assert risk.risk_for("moirai") == "medium"


def test_an_approved_proposal_actually_runs_the_workflow(monkeypatch):
    from birkin import approvals
    ran = {}

    def fake_run(script, **kw):
        ran["script"] = script.name
        ran["args"] = kw.get("args")
        return {"status": "completed", "agents": 2, "seconds": 1.0,
                "run_id": "rid"}

    monkeypatch.setattr("birkin.moirai.engine.run_script", fake_run)
    out = approvals.execute_action(
        "moirai", {"script": "cross-examine", "task": "무엇을 비교"})
    assert ran["script"] == "cross-examine"
    assert ran["args"]["task"] == "무엇을 비교"
    assert "completed" in out and "rid" in out


def test_an_approved_proposal_naming_a_missing_workflow_fails_loudly():
    from birkin import approvals
    out = approvals.execute_action("moirai", {"script": "no-such-workflow"})
    assert "찾을 수 없습니다" in out


def test_an_empty_payload_does_not_crash_the_executor():
    from birkin import approvals
    assert "지정되지" in approvals.execute_action("moirai", {})


# ---------------- the invariant that must survive -------------------------

def test_no_tool_exposes_moirai_to_a_model():
    """The model may propose; it may never spawn. That is the whole rail.

    Checked structurally rather than by grepping for the word: no tool module
    may name the moirai package in an import or any other identifier. The one
    place the word is allowed to survive is files.py's write deny-list, which
    shuts the door (a planted script under ~/.birkin/moirai/ would be exec()d)
    rather than opening one.
    """
    import ast
    import pathlib
    from birkin.tools import files
    tools = pathlib.Path(__file__).resolve().parent.parent / "birkin" / "tools"
    for f in tools.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            ident = (
                node.id if isinstance(node, ast.Name)
                else node.attr if isinstance(node, ast.Attribute)
                else node.name if isinstance(node, ast.alias)
                else node.module if isinstance(node, ast.ImportFrom)
                else None
            )
            assert ident is None or "moirai" not in ident, f.name
        if "moirai" in src:
            assert f.name == "files.py", f.name
    assert "cannot write" in files._CONTROL_DIRS["moirai"]


# ---------------- the note must ask for output something consumes ---------

def test_the_note_never_asks_for_an_envelope_nothing_parses():
    """R60: `parse`/`queue` have no production caller on any surface.

    A note that demands the envelope makes an opted-in user's turn come back
    as raw markup with their question unanswered, so the note must ask for
    the one thing that does reach a human: prose naming the CLI command.
    """
    note = T.auto_trigger_note({"moirai_auto": True})
    assert T.PROPOSAL_OPEN not in note and T.PROPOSAL_CLOSE not in note
    on = {"moirai_auto": True}
    for surface in (promptgate.compose_main(on, skills_index="s",
                                            memory_block=""),
                    promptgate.compose_cli(on, memory_block="")):
        assert T.PROPOSAL_OPEN not in surface
        assert "birkin moirai run" in surface
