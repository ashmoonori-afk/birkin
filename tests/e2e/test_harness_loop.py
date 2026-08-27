"""End-to-end: a proposal becomes a durable, visible, reversible refinement.

Every unit test in the harness suite proves one link. This one proves the chain
the design exists for (docs/prime-agent-analysis.html section 4): a proposal is
applied, lands on disk, reaches the system prompt the model actually receives,
shows up in the CLI a human uses, and comes back out again on rollback -- with
the prior state restored byte-for-byte.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import birkin
from birkin import cli, harness, promptgate, runtime

_REPO = Path(birkin.__file__).resolve().parent.parent


def _proposal(*edits, summary="nightly pass", rationale="observed three times",
              outcome="fixture omissions stop recurring"):
    return {"summary": summary, "rationale": rationale,
            "expectedOutcome": outcome, "edits": list(edits)}


def _create(kind, title, content, reason="observed three times"):
    return {"action": "create", "kind": kind, "title": title,
            "content": content, "reason": reason}


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "birkin", *args],
        cwd=str(_REPO), capture_output=True, text=True, timeout=180,
        errors="replace", env={**os.environ})


def test_the_whole_loop_from_proposal_to_rollback(capsys):
    session_id = "e2e-loop"
    cfg = {"harness_enabled": True, "session_id": session_id,
           "harness_auto_approve": ["memory", "skill_note"],
           "harness_max_edits": 12, "harness_prompt_budget": 20000}

    assert harness.state_path("local", session_id=session_id).exists() is False

    seeded = harness.submit(_proposal(
        _create("memory", "Test layout", "Tests live in tests/, e2e in tests/e2e."),
        _create("skill_note", "Release audit", "Check both READMEs before a push."),
    ), cfg=cfg, scope="local", session_id=session_id)
    assert seeded["queued"] == []
    assert seeded["rejected"] == []
    baseline_entries = copy.deepcopy(
        harness.load("local", session_id=session_id)["entries"],
    )

    applied = harness.submit(_proposal(
        _create("memory", "Deploy note", "The daemon must be restarted after update."),
        {"action": "update", "kind": "memory", "id": "test_layout",
         "content": "Tests live in tests/; the e2e loop lives in tests/e2e.",
         "reason": "layout clarified"},
    ), cfg=cfg, scope="local", session_id=session_id)
    rid = applied["applied"]["id"]

    path = harness.state_path("local", session_id=session_id)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["entries"]["memory"]["deploy_note"]["version"] == 1
    assert on_disk["entries"]["memory"]["test_layout"]["version"] == 2
    assert any(event["id"] == rid for event in on_disk["refinements"])

    block = runtime._harness_block(cfg)
    prompt = promptgate.compose_main(cfg, memory_block="likes brevity",
                                     harness_block=block)
    assert "Deploy note" in prompt
    assert "Release audit" in prompt
    assert rid in prompt
    assert len(block) <= cfg["harness_prompt_budget"]

    local_args = ["--scope", "local", "--session-id", session_id]
    assert cli.main(["harness", "show", *local_args]) == 0
    shown = capsys.readouterr().out
    assert "Deploy note" in shown

    assert cli.main(["harness", "history", *local_args]) == 0
    listed = capsys.readouterr().out
    assert rid in listed

    assert cli.main(["harness", "rollback", rid, *local_args]) == 0
    rolled = capsys.readouterr().out
    assert rid in rolled

    restored = harness.load("local", session_id=session_id)["entries"]
    assert set(restored["memory"]) == set(baseline_entries["memory"])
    for eid, before in baseline_entries["memory"].items():
        for field in ("title", "content", "path", "kind", "scope"):
            assert restored["memory"][eid][field] == before[field]
    assert restored["skill_note"] == baseline_entries["skill_note"]
    assert any(
        event.get("rollback_of") == rid
        for event in harness.history("local", session_id=session_id)
    )


def test_rollback_counts_as_a_refinement_rather_than_erasing_history():
    """An undo is itself a recorded change: the version keeps climbing.

    Resetting ``version`` back would make the ledger lie -- two entries with the
    same version and different content, and no way to tell an original from a
    restored one. The restored *content* matches; the bookkeeping does not.
    """
    session_id = "e2e-rollback"
    cfg = {"harness_enabled": True, "harness_auto_approve": ["memory"],
           "harness_max_edits": 12}
    harness.submit(_proposal(
        _create("memory", "Layout", "original")), cfg=cfg,
        scope="local", session_id=session_id)

    changed = harness.submit(_proposal(
        {"action": "update", "kind": "memory", "id": "layout",
         "content": "edited", "reason": "drift"}), cfg=cfg,
        scope="local", session_id=session_id)
    harness.rollback(
        changed["applied"]["id"], "local", session_id=session_id,
    )

    entry = harness.load(
        "local", session_id=session_id,
    )["entries"]["memory"]["layout"]
    assert entry["content"] == "original"
    assert entry["version"] == 3
    assert entry["source"] == "rollback"


def test_a_prompt_edit_waits_for_review_before_it_can_steer_the_agent():
    from birkin import approvals, store

    cfg = {"harness_enabled": True, "harness_auto_approve": ["memory", "skill"],
           "harness_max_edits": 12, "harness_prompt_budget": 20000}

    result = harness.submit(_proposal(
        _create("prompt", "Check git status",
                "Run git status before every commit.")), cfg=cfg)

    assert result["applied"] is None
    assert "Check git status" not in promptgate.compose_main(
        cfg, harness_block=runtime._harness_block(cfg))

    aid = store.list_pending()[0]["id"]
    assert approvals.approve(aid, approved_by="human:test", approved_via="test")["ok"] is True

    assert "Check git status" in promptgate.compose_main(
        cfg, harness_block=runtime._harness_block(cfg))


def test_the_real_cli_reports_an_empty_harness_and_rejects_a_bogus_id():
    empty = _run_cli("harness", "history")
    assert empty.returncode == 0, empty.stdout + empty.stderr
    assert "No refinements" in empty.stdout

    bogus = _run_cli("harness", "rollback", "rf_does_not_exist")
    assert bogus.returncode == 1, bogus.stdout + bogus.stderr
    assert "rf_does_not_exist" in (bogus.stdout + bogus.stderr)
    assert "Traceback" not in (bogus.stdout + bogus.stderr)


def test_the_real_cli_exports_the_state_it_was_given(tmp_path):
    cfg = {"harness_enabled": True, "harness_auto_approve": ["memory"],
           "harness_max_edits": 12}
    harness.submit(_proposal(
        _create("memory", "Exported fact", "Worth keeping.")), cfg=cfg,
        scope="local", session_id="e2e-export")

    target = tmp_path / "harness-export.json"
    done = _run_cli(
        "harness", "export", str(target),
        "--scope", "local",
        "--session-id", "e2e-export",
    )
    assert done.returncode == 0, done.stdout + done.stderr

    exported = json.loads(target.read_text(encoding="utf-8"))
    assert exported["entries"]["memory"]["exported_fact"]["content"] == \
        "Worth keeping."
