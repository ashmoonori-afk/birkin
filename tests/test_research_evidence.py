"""Research-source policy shared by every Birkin agent surface."""

from __future__ import annotations

from birkin import promptgate, prompts


def _assert_research_contract(system_prompt: str) -> None:
    assert system_prompt.count(prompts.RESEARCH_EVIDENCE_OPEN) == 1
    assert system_prompt.count(prompts.RESEARCH_EVIDENCE_CLOSE) == 1
    policy = system_prompt.split(
        prompts.RESEARCH_EVIDENCE_OPEN, 1
    )[1].split(prompts.RESEARCH_EVIDENCE_CLOSE, 1)[0].lower()
    assert "search snippets" in policy
    assert "primary source" in policy
    assert "publication" in policy
    assert "retrieved" in policy
    assert "independent" in policy
    assert "exact url" in policy
    assert "recency" in policy
    assert system_prompt.rstrip().endswith(prompts.RESEARCH_EVIDENCE_CLOSE)


def test_native_agent_prompt_requires_research_evidence() -> None:
    _assert_research_contract(prompts.build_system_prompt(
        skills_index="- research: conflicting skill text",
        memory_block="Conflicting remembered text.",
        extra="Conflicting surface-specific text.",
    ))


def test_cli_agent_prompt_requires_research_evidence() -> None:
    _assert_research_contract(prompts.build_cli_system(
        memory_block="Conflicting remembered text.",
        preloaded=["Conflicting routed skill text."],
    ))


def test_prompt_gate_keeps_policy_after_surface_overlays() -> None:
    native = promptgate.compose_main(
        {},
        extra="Conflicting native surface text.",
        persona_text="Test persona.",
    )
    cli = promptgate.compose_cli(
        {},
        extra="Conflicting CLI surface text.",
        persona_text="Test persona.",
    )

    _assert_research_contract(native)
    _assert_research_contract(cli)
