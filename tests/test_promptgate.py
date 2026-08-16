"""Prompt-Gate (v2 #7) — single system-prompt assembler + static audit."""

from __future__ import annotations

from pathlib import Path

import birkin
from birkin import goals, harness, ide, promptgate


def test_compose_main_includes_persona_and_neurosis_note():
    out = promptgate.compose_main({"neurosis_auto": True}, persona_text="ARRR pirate",
                                  memory_block="likes brevity")
    assert "ARRR pirate" in out                       # persona slot
    assert "when to run it automatically" in out.lower()   # neurosis note appended
    assert "likes brevity" in out


def test_compose_cli_appends_extra_before_note():
    out = promptgate.compose_cli({"neurosis_auto": True}, persona_text="voice",
                                 extra="\n\nEXTRA-BLOCK")
    assert "voice" in out and "EXTRA-BLOCK" in out
    # the neurosis note is appended AFTER the extra block
    assert out.index("EXTRA-BLOCK") < out.lower().index("when to run it automatically")


def test_active_goal_reaches_every_composed_prompt():
    goals.set_goal("Ship the release blockers", gate="python -m pytest")

    for out in (promptgate.compose_main({"neurosis_auto": False},
                                        persona_text=""),
                promptgate.compose_cli({"neurosis_auto": False},
                                       persona_text="")):
        assert "Ship the release blockers" in out
        assert "python -m pytest" in out

    goals.pause()
    assert "Ship the release blockers" not in promptgate.compose_main(
        {"neurosis_auto": False}, persona_text="")


def test_global_goal_fallback_can_be_disabled_for_isolated_sessions():
    goals.set_goal("Private local goal")

    local = promptgate.compose_main(
        {"neurosis_auto": False, "session_id": "local-session"},
        persona_text="",
    )
    isolated = promptgate.compose_main(
        {
            "neurosis_auto": False,
            "session_id": "gateway-session",
            "session_goal_fallback": False,
        },
        persona_text="",
    )

    assert "Private local goal" in local
    assert "Private local goal" not in isolated


def test_session_working_state_reaches_only_matching_prompts():
    goals.set_goal("First session goal", session_id="session-one")
    harness.update_working(
        "session-one",
        corrections=["Honor the latest correction"],
        next_actions=["Run the matching scenario"],
    )

    matching = promptgate.compose_main(
        {"neurosis_auto": False, "session_id": "session-one"},
        persona_text="",
    )
    other = promptgate.compose_main(
        {"neurosis_auto": False, "session_id": "session-two"},
        persona_text="",
    )

    assert "First session goal" in matching
    assert "Honor the latest correction" in matching
    assert "Run the matching scenario" in matching
    assert "First session goal" not in other
    assert "Honor the latest correction" not in other


def test_turn_context_refreshes_warm_session_working_state():
    cfg = {"session_id": "warm-session"}
    first = promptgate.compose_turn_context(cfg)
    harness.update_working(
        "warm-session",
        decisions=["Use the canonical harness journal"],
    )
    second = promptgate.compose_turn_context(cfg)

    assert "canonical harness journal" not in first
    assert "canonical harness journal" in second


def test_turn_context_emits_reset_marker_after_clear():
    session_id = "warm-clear"
    harness.update_working(
        session_id,
        decisions=["stale decision"],
    )
    assert "stale decision" in promptgate.compose_turn_context({
        "session_id": session_id,
    })

    assert harness.clear_working(session_id)
    cleared = promptgate.compose_turn_context({"session_id": session_id})

    assert "stale decision" not in cleared
    assert "<working-memory-reset" in cleared
    assert 'revision="0"' in cleared


def test_turn_context_emits_goal_reset_while_journal_remains():
    session_id = "goal-clear"
    goals.set_goal("stale goal", session_id=session_id)
    harness.update_working(
        session_id,
        decisions=["journal remains"],
    )
    assert "stale goal" in promptgate.compose_turn_context({
        "session_id": session_id,
    })

    goals.pause(session_id=session_id)
    cleared = promptgate.compose_turn_context({"session_id": session_id})

    assert "stale goal" not in cleared
    assert "<active-goal-reset" in cleared
    assert "journal remains" in cleared


def test_neurosis_note_off_when_disabled():
    out = promptgate.compose_main({"neurosis_auto": False}, persona_text="x")
    assert "when to run it automatically" not in out.lower()


def test_enforced_cli_prompt_scrubs_unavailable_skill_tool_ids():
    out = promptgate.compose_cli(
        {
            "egress": {"enabled": True, "enforced": True},
            "neurosis_auto": False,
        },
        persona_text="",
        preloaded=["Use `run_shell` to validate the result."],
    )

    assert "run_shell" not in out


def test_public_prompt_bypasses_workspace_files_and_ide_context(
        monkeypatch, tmp_path):
    for name in ("SOUL.md", "AGENTS.md", "TOOLS.md"):
        (tmp_path / name).write_text(
            f"PRIVATE {name} SENTINEL",
            encoding="utf-8",
        )
    monkeypatch.chdir(tmp_path)
    ide_calls: list[bool] = []
    monkeypatch.setattr(
        ide,
        "consume_context_note",
        lambda: ide_calls.append(True) or "PRIVATE IDE SENTINEL",
    )

    out = promptgate.compose_public()

    assert "You are birkin" in out
    assert "PRIVATE" not in out
    assert ide_calls == []


def test_static_audit_main_turn_prompt_goes_through_the_gate():
    """The PRIMARY conversational system prompt (REPL/gateway/dry-run, both
    provider paths) must be assembled via promptgate. Exempt: prompts.py (defs),
    promptgate.py (the gate), and the intentionally-specialized
    selfimprove.py extraction prompts. Matches on the ``prompts.`` prefix so the local method name
    ``_build_cli_system`` is not a false positive."""
    pkg = Path(birkin.__file__).parent
    allowed = {"promptgate.py", "prompts.py", "selfimprove.py"}
    offenders = []
    for py in pkg.rglob("*.py"):
        if py.name in allowed or "__pycache__" in py.parts:
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        if "prompts.build_system_prompt(" in text or "prompts.build_cli_system(" in text:
            offenders.append(str(py.relative_to(pkg)))
    assert offenders == [], (
        "these modules bypass the Prompt-Gate (route them through promptgate): "
        + ", ".join(offenders))
