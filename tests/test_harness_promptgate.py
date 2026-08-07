"""The harness block reaches the real system prompt through the Prompt-Gate.

`runtime.py` may not call `prompts.build_system_prompt` directly -- the static
audit in test_promptgate.py fails any module that bypasses the gate. So the
harness slot only exists end-to-end if `promptgate.compose_main` forwards it;
routing it through `extra=` would work today but collides with the callers that
already use `extra` for their own text.
"""

from __future__ import annotations

from birkin import harness, promptgate, prompts


def _seed_entry() -> None:
    harness.apply(harness.load(),
                  {"summary": "s", "rationale": "r", "expectedOutcome": "o",
                   "edits": [{"action": "create", "kind": "prompt",
                              "title": "Check git status",
                              "content": "Run git status before committing.",
                              "reason": "observed twice"}]},
                  baseline=harness.load(), scope="global", rid="rf_pg")


def test_compose_main_forwards_the_harness_block():
    out = promptgate.compose_main({}, harness_block="## Harness (test)")
    assert "## Harness (test)" in out


def test_harness_block_and_extra_coexist():
    out = promptgate.compose_main({}, memory_block="likes brevity",
                                  harness_block="## Harness (test)",
                                  extra="EXTRA-BLOCK")
    assert out.index("likes brevity") < out.index("## Harness (test)")
    assert out.index("## Harness (test)") < out.index("EXTRA-BLOCK")


def test_the_sealed_policy_still_ends_the_prompt():
    out = promptgate.compose_main({}, harness_block="## Harness (test)")
    assert out.rstrip().endswith(prompts.RESEARCH_EVIDENCE_POLICY.rstrip())


def test_an_empty_harness_block_changes_nothing():
    assert promptgate.compose_main({}, harness_block="") == \
        promptgate.compose_main({})


def test_a_real_harness_entry_reaches_the_session_prompt():
    _seed_entry()
    from birkin import runtime

    block = runtime._harness_block({"harness_enabled": True})
    assert "Check git status" in block
    assert "Check git status" in promptgate.compose_main({}, harness_block=block)


def test_the_block_is_empty_when_the_harness_is_disabled():
    _seed_entry()
    from birkin import runtime

    assert runtime._harness_block({"harness_enabled": False}) == ""
