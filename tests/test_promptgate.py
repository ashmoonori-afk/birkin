"""Prompt-Gate (v2 #7) — single system-prompt assembler + static audit."""

from __future__ import annotations

from pathlib import Path

import birkin
from birkin import promptgate


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
