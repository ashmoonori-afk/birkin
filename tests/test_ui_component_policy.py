"""Default UI component reference shared by every Birkin agent surface."""

from __future__ import annotations

from birkin import promptgate, prompts


def _assert_shadcn_contract(system_prompt: str) -> None:
    assert system_prompt.count(prompts.UI_COMPONENT_POLICY_OPEN) == 1
    assert system_prompt.count(prompts.UI_COMPONENT_POLICY_CLOSE) == 1
    policy = system_prompt.split(
        prompts.UI_COMPONENT_POLICY_OPEN, 1
    )[1].split(prompts.UI_COMPONENT_POLICY_CLOSE, 1)[0].lower()
    assert "shadcn/ui" in policy
    assert "https://ui.shadcn.com/docs/components" in policy
    assert "default component book" in policy
    assert "react" in policy and "tailwind" in policy
    assert "standalone html" in policy
    assert "accessibility" in policy
    assert "dependency" in policy


def test_native_agent_uses_shadcn_as_default_component_book() -> None:
    _assert_shadcn_contract(prompts.build_system_prompt())


def test_cli_agent_uses_shadcn_as_default_component_book() -> None:
    _assert_shadcn_contract(prompts.build_cli_system())


def test_prompt_gate_preserves_shadcn_component_policy() -> None:
    _assert_shadcn_contract(promptgate.compose_main({}))
    _assert_shadcn_contract(promptgate.compose_cli({}))
