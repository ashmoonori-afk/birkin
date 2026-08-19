"""Issue-tree pattern: bounded MECE decomposition, leaf execution, bottom-up join.

The contract under test is structural, not prose: the depth/leaf caps are
enforced in CODE (a planner that over-grows the tree is rejected, not
prompted harder), leaves run in parent-ordered sibling groups, worker
follow-ups join the ledger instead of vanishing, and the report names every
leaf's status. No live models -- `spawn` is injected, following
test_moirai_core.py's precedent.
"""

from __future__ import annotations

import json

import pytest

from birkin import moirai
from birkin.moirai import cli as moirai_cli
from birkin.moirai.patterns import issue_tree


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


@pytest.fixture
def script():
    return moirai.load_script(moirai_cli.resolve_script_path("issue-tree"))


def _spawn(replies):
    """Answer by prompt substring; dicts ship as JSON like a real completer."""
    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        for key, value in replies.items():
            if key in prompt:
                return (value if isinstance(value, str)
                        else json.dumps(value, ensure_ascii=False))
        return json.dumps({"result": "ok", "followups": []},
                          ensure_ascii=False)
    return spawn


# A two-level tree: root -> A, B; A -> a1, a2; B -> b1. Three leaves.
TREE = {
    "goal": "goal",
    "children": [
        {"title": "A", "children": [
            {"title": "a1", "leaf": True},
            {"title": "a2", "leaf": True}]},
        {"title": "B", "children": [
            {"title": "b1", "leaf": True}]},
    ],
}


# ---------------- tree validation (code-level caps) -----------------------

def test_a_deeper_tree_than_the_cap_is_rejected(script):
    deep = {"goal": "g", "children": [
        {"title": "x", "children": [
            {"title": "y", "children": [
                {"title": "z", "children": [
                    {"title": "w", "leaf": True}]}]}]}]}
    out = moirai.run_script(script, cfg={}, args={"task": "t"},
                            spawn=_spawn({"MECE": deep}))
    assert out["status"] == "completed"
    assert "tree rejected" in out["result"]["error"]
    assert "depth cap" in out["result"]["error"]


def test_a_tree_with_more_leaves_than_the_cap_is_rejected(script):
    wide = {"goal": "g", "children": [
        {"title": f"leaf-{i}", "leaf": True} for i in range(13)]}
    out = moirai.run_script(script, cfg={}, args={"task": "t"},
                            spawn=_spawn({"MECE": wide}))
    assert "tree rejected" in out["result"]["error"]
    assert "leaf cap" in out["result"]["error"]


def test_args_can_only_tighten_the_caps(script):
    # 5 leaves is fine by default, over an arg cap of 2 -> rejected.
    five = {"goal": "g", "children": [
        {"title": f"leaf-{i}", "leaf": True} for i in range(5)]}
    out = moirai.run_script(script, cfg={},
                            args={"task": "t", "max_leaves": 2},
                            spawn=_spawn({"MECE": five}))
    assert "leaf cap" in out["result"]["error"]
    # ... and the same tree passes when the arg allows it.
    ok = moirai.run_script(script, cfg={},
                           args={"task": "t", "max_leaves": 5},
                           spawn=_spawn({"MECE": five}))
    assert "error" not in ok["result"]


def test_a_planner_failure_or_shapeless_answer_is_a_clean_rejection(script):
    out = moirai.run_script(script, cfg={}, args={"task": "t"},
                            spawn=_spawn({"MECE": "not json at all"}))
    assert "tree rejected" in out["result"]["error"]


def test_the_ceiling_itself_is_enforced_in_code():
    root, err = issue_tree._parse_tree(
        {"goal": "g", "children": [{"title": f"l{i}", "leaf": True}
                                   for i in range(20)]},
        max_depth=issue_tree.MAX_DEPTH, max_leaves=issue_tree.MAX_LEAVES)
    assert root is None and "leaf cap" in err
    assert issue_tree.MAX_DEPTH <= 3 and issue_tree.MAX_LEAVES <= 12


# ---------------- leaf scheduling order -----------------------------------

def test_leaves_run_in_sibling_groups_in_parent_order(script):
    order = []

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        if "MECE" in prompt:
            return json.dumps(TREE)
        for title in ("a1", "a2", "b1"):
            if f"leaf:{title}" in prompt or f"잎 이슈: {title}" in prompt:
                order.append(title)
                return json.dumps({"result": f"done {title}",
                                   "followups": []})
        if "상향식으로 취합" in prompt:
            return json.dumps({"summary": "joined"})
        return json.dumps({"result": "ok", "followups": []})

    out = moirai.run_script(script, cfg={"moirai_workers": 1},
                            args={"task": "t"}, spawn=spawn)
    assert out["status"] == "completed"
    # A's leaves before B's leaf (parent order); within a group, order kept.
    assert order == ["a1", "a2", "b1"]


def test_group_boundaries_match_the_tree_shape(script):
    groups = []
    root, err = issue_tree._parse_tree(TREE, max_depth=3, max_leaves=12)
    assert err is None
    issue_tree._sibling_groups(root, groups)
    assert [[n.title for n in g] for g in groups] == [["a1", "a2"], ["b1"]]


# ---------------- follow-up join ------------------------------------------

def test_worker_followups_join_the_ledger_and_run(script):
    ran = []

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        if "MECE" in prompt:
            return json.dumps({"goal": "g", "children": [
                {"title": "only", "leaf": True}]})
        if "잎 이슈: only" in prompt:
            ran.append("only")
            return json.dumps({"result": "done",
                               "followups": ["fix the thing found"]})
        if "후속으로 발견된 잎 이슈: fix the thing found" in prompt:
            ran.append("fix the thing found")
            return json.dumps({"result": "fixed", "followups": []})
        if "상향식으로 취합" in prompt:
            return json.dumps({"summary": "s"})
        return json.dumps({"result": "ok", "followups": []})

    out = moirai.run_script(script, cfg={}, args={"task": "t"}, spawn=spawn)
    assert ran == ["only", "fix the thing found"]
    assert "fix the thing found" in out["result"]


def test_followups_beyond_the_cap_are_dropped_and_named(script):
    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        if "MECE" in prompt:
            return json.dumps({"goal": "g", "children": [
                {"title": "only", "leaf": True}]})
        if "잎 이슈: only" in prompt:
            return json.dumps({"result": "done",
                               "followups": [f"extra-{i}" for i in range(5)]})
        if "후속으로 발견된 잎 이슈: extra-0" in prompt:
            # the first follow-up tries to grow the list past the cap
            return json.dumps({"result": "done",
                               "followups": [f"flood-{i}" for i in range(
                                   issue_tree.MAX_FOLLOWUPS + 5)]})
        if "상향식으로 취합" in prompt:
            return json.dumps({"summary": "s"})
        return json.dumps({"result": "done", "followups": []})

    out = moirai.run_script(script, cfg={}, args={"task": "t"}, spawn=spawn)
    assert out["status"] == "completed"
    assert "cap" in out["result"]
    assert "flood-" in out["result"], "dropped follow-ups must be named"


# ---------------- report coverage ------------------------------------------

def test_the_report_covers_every_leaf_status(script):
    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        if "MECE" in prompt:
            return json.dumps(TREE)
        if "잎 이슈: a2" in prompt:
            raise RuntimeError("worker died")
        for title in ("a1", "b1"):
            if f"잎 이슈: {title}" in prompt:
                return json.dumps({"result": f"done {title}",
                                   "followups": []})
        if "상향식으로 취합" in prompt:
            return json.dumps({"summary": "joined summary"})
        return json.dumps({"result": "ok", "followups": []})

    out = moirai.run_script(script, cfg={}, args={"task": "t"}, spawn=spawn)
    report = out["result"]
    assert out["status"] == "completed", "one dead leaf must not kill the run"
    assert report.startswith("VERDICT:"), "Minto: verdict line first"
    for title, status in (("a1", "done"), ("a2", "failed"), ("b1", "done")):
        assert f"[{status}] {title}" in report, (
            f"report must name leaf {title} with status {status}")
    assert "joined summary" in report          # bottom-up judge output


def test_a_fully_successful_tree_reports_verdict_done(script):
    replies = {
        "MECE": TREE,
        "잎 이슈:": {"result": "fine", "followups": []},
        "상향식으로 취합": {"summary": "all good"},
    }
    out = moirai.run_script(script, cfg={}, args={"task": "t"},
                            spawn=_spawn(replies))
    assert out["result"].splitlines()[0].startswith("VERDICT: 완료")


# ---------------- meta / resolution ----------------------------------------

def test_the_pattern_is_resolvable_by_name_and_declares_its_roles(script):
    assert moirai_cli.resolve_script_path("issue_tree").is_file()
    assert set(script.roles) == {"planner", "worker", "judge"}
    assert script.meta["phases"] == ["Plan", "Execute", "Report"]
