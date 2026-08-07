"""Morpheus emits its harness proposal as TEXT and Python applies it.

Why this exists: the nightly used to persist only through MCP tool calls, and
`codex exec` CANCELS every MCP tool call — so on that provider the run produced
prose and saved nothing. A proposal returned as a fenced ```json block is parsed
and applied by :mod:`birkin.harness`, which needs no tool call at all.

Nothing here touches a provider: the parser and the submit wrapper are driven
with fake summary strings, and the two run paths with a faked ``ask``.
"""

from __future__ import annotations

import json

from birkin import config, harness, morpheus, store

_MEMORY_EDIT = {"action": "create", "kind": "memory",
                "title": "Nightly deploy ritual",
                "content": "user runs `make deploy` at 23:00 before sleeping",
                "reason": "repeated three times in the last 24h"}


def _summary(proposal: dict, *, prose: str = "Learned two things tonight.") -> str:
    """A realistic morpheus summary: prose first, one fenced block last."""
    return f"{prose}\n\n```json\n{json.dumps(proposal, ensure_ascii=False)}\n```\n"


def _proposal(edits: list[dict]) -> dict:
    return {"summary": "capture the nightly deploy ritual",
            "rationale": "the user repeated it three times",
            "expectedOutcome": "tomorrow's run already knows the ritual",
            "edits": edits}


# ---------------- parse + apply -------------------------------------------

def test_valid_fenced_proposal_lands_in_the_harness_ledger():
    cfg = config.load_config()

    details = morpheus._apply_harness_proposal(
        cfg, _summary(_proposal([_MEMORY_EDIT])), dry_run=False)

    assert details is not None
    assert details["changes"] == ["create memory:nightly_deploy_ritual"]
    assert details["refinement"]
    state = harness.load("global")
    assert "nightly_deploy_ritual" in state["entries"]["memory"]
    assert harness.state_path("global").is_file()
    assert harness.history_path("global").is_file()   # refinements.jsonl


def test_non_auto_kinds_are_queued_for_review_not_written():
    """`prompt` is outside harness_auto_approve, so it goes to the gate."""
    cfg = config.load_config()

    details = morpheus._apply_harness_proposal(
        cfg,
        _summary(_proposal([{"action": "create", "kind": "prompt",
                             "title": "Answer in Korean",
                             "content": "prefer Korean for this user"}])),
        dry_run=False)

    assert details is not None
    assert details["changes"] == []
    assert len(details["queued"]) == 1
    assert harness.load("global")["entries"]["prompt"] == {}
    assert any(p["category"] == "harness" for p in store.list_pending())


def test_summary_without_a_json_block_is_a_noop():
    cfg = config.load_config()
    text = "Quiet night. Nothing structured to record."

    assert morpheus._harness_proposal(text) is None
    assert morpheus._apply_harness_proposal(cfg, text, dry_run=False) is None
    assert harness.state_path("global").exists() is False


def test_truncated_json_block_is_a_noop_not_an_exception():
    cfg = config.load_config()
    text = ('Learned one thing.\n\n```json\n'
            '{"summary": "x", "edits": [{"action": "create", "kind": "memo\n')

    assert morpheus._harness_proposal(text) is None
    assert morpheus._apply_harness_proposal(cfg, text, dry_run=False) is None
    assert harness.state_path("global").exists() is False


def test_json_block_without_edits_is_a_noop():
    cfg = config.load_config()
    text = 'Done.\n\n```json\n{"summary": "no refinement tonight"}\n```\n'

    assert morpheus._harness_proposal(text) is None
    assert morpheus._apply_harness_proposal(cfg, text, dry_run=False) is None
    assert harness.state_path("global").exists() is False


def test_last_well_formed_block_wins():
    """A model that echoes the example block first must not beat its own answer."""
    text = ('Here is the shape:\n\n```json\n{"summary": "example", "edits": []}\n'
            '```\n\nAnd my proposal:\n\n```json\n'
            + json.dumps(_proposal([_MEMORY_EDIT])) + "\n```\n")

    parsed = morpheus._harness_proposal(text)

    assert parsed is not None
    assert parsed["summary"] == "capture the nightly deploy ritual"


def test_edits_are_capped_at_harness_max_edits():
    cfg = {**config.load_config(), "harness_max_edits": 3}
    edits = [{"action": "create", "kind": "memory", "title": f"Fact {i}",
              "content": f"body {i}"} for i in range(10)]

    details = morpheus._apply_harness_proposal(
        cfg, _summary(_proposal(edits)), dry_run=False)

    assert details is not None
    assert len(details["changes"]) == 3
    assert len(harness.load("global")["entries"]["memory"]) == 3


def test_invalid_edits_are_rejected_without_killing_the_valid_ones():
    cfg = config.load_config()

    details = morpheus._apply_harness_proposal(
        cfg,
        _summary(_proposal([{"action": "obliterate", "kind": "memory",
                             "title": "bad", "content": "x"},
                            _MEMORY_EDIT])),
        dry_run=False)

    assert details is not None
    assert details["changes"] == ["create memory:nightly_deploy_ritual"]
    assert details["rejected"] == ["unknown action 'obliterate'"]


def test_harness_disabled_means_no_writes():
    cfg = {**config.load_config(), "harness_enabled": False}

    assert morpheus._apply_harness_proposal(
        cfg, _summary(_proposal([_MEMORY_EDIT])), dry_run=False) is None
    assert harness.state_path("global").exists() is False


# ---------------- dry run --------------------------------------------------

def test_dry_run_writes_no_harness_state():
    cfg = config.load_config()

    assert morpheus._apply_harness_proposal(
        cfg, _summary(_proposal([_MEMORY_EDIT])), dry_run=True) is None
    assert harness.state_path("global").exists() is False
    assert harness.history_path("global").exists() is False
    assert store.list_pending() == []


def test_dry_run_through_the_generic_path_persists_nothing(monkeypatch):
    from birkin.runtime import build_session

    cfg = {**config.DEFAULT_CONFIG, "provider": "codex-cli", "model": "",
           "cli_access": "workspace"}
    session = build_session(cfg)
    monkeypatch.setattr(morpheus, "build_session", lambda _cfg: session)
    monkeypatch.setattr(
        session, "ask",
        lambda _task, **_kw: _summary(_proposal([_MEMORY_EDIT])))

    rc = morpheus._run_birkin_morpheus(cfg, "task", True, 0)

    assert rc == 0
    assert harness.state_path("global").exists() is False
    assert harness.history_path("global").exists() is False
    assert store.list_pending() == []
    assert store.list_runs(limit=5) == []


# ---------------- run record is the audit trail ----------------------------

def test_generic_run_record_details_carry_the_applied_changes(monkeypatch):
    from birkin.runtime import build_session

    cfg = {**config.DEFAULT_CONFIG, "provider": "codex-cli", "model": "",
           "cli_access": "workspace"}
    session = build_session(cfg)
    monkeypatch.setattr(morpheus, "build_session", lambda _cfg: session)
    monkeypatch.setattr(
        session, "ask",
        lambda _task, **_kw: _summary(_proposal([_MEMORY_EDIT])))

    rc = morpheus._run_birkin_morpheus(cfg, "task", False, 0)

    assert rc == 0
    record = next(r for r in store.list_runs(limit=5) if r["kind"] == "morpheus")
    entry = record["details"]["harness"]
    assert entry["changes"] == ["create memory:nightly_deploy_ritual"]
    assert entry["refinement"] == harness.load("global")["refinements"][-1]["id"]


def test_claude_path_applies_and_records_the_proposal(monkeypatch):
    text = _summary(_proposal([_MEMORY_EDIT]))

    class _Session:
        def __init__(self, **_kwargs):
            pass

        def ask(self, _task):
            return text

        def close(self):
            pass

    monkeypatch.setattr("birkin.claude_session.ClaudeStreamSession", _Session)
    cfg = {**config.DEFAULT_CONFIG, "provider": "claude-cli"}

    rc = morpheus._run_claude_morpheus(cfg, "task", False, 0)

    assert rc == 0
    assert "nightly_deploy_ritual" in harness.load("global")["entries"]["memory"]
    record = next(r for r in store.list_runs(limit=5) if r["kind"] == "morpheus")
    assert record["details"]["harness"]["changes"] == [
        "create memory:nightly_deploy_ritual"]


def test_claude_dry_run_writes_no_harness_state(monkeypatch):
    class _Session:
        def __init__(self, **_kwargs):
            pass

        def ask(self, _task):
            return _summary(_proposal([_MEMORY_EDIT]))

        def close(self):
            pass

    monkeypatch.setattr("birkin.claude_session.ClaudeStreamSession", _Session)

    rc = morpheus._run_claude_morpheus(
        {**config.DEFAULT_CONFIG, "provider": "claude-cli"}, "task", True, 0)

    assert rc == 0
    assert harness.state_path("global").exists() is False
    assert store.list_runs(limit=5) == []


# ---------------- the prompt contract --------------------------------------

def test_task_prompt_documents_the_block_the_parser_reads():
    rendered = morpheus._MORPHEUS_TASK.format(
        date="2026-08-07", dry="", sessions="(none)", files="(none)",
        activity="(none)", memory_state="(none)", skill_state="(none)")

    example = morpheus._harness_proposal(rendered)

    assert example is not None, "the prompt must show a block the parser accepts"
    assert set(example) >= {"summary", "rationale", "expectedOutcome", "edits"}
    assert set(example["edits"][0]) >= {"action", "kind", "title", "content"}
    # the new block is additive: tool instructions and the security boundary stay
    assert "propose_action" in rendered
    assert "memory_write_note" in rendered
    assert "<<<BEGIN UNTRUSTED DATA>>>" in rendered
