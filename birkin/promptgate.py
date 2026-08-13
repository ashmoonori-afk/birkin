"""Prompt-Gate (v2 #7) — the ONE place birkin assembles a system prompt.

Persona (SOUL.md) + memory + skills + the neurosis auto-trigger note were being
stitched together in several spots (runtime API path, runtime CLI path, the
gateway warm session, the dry-run packet), risking drift. Every surface now
composes its system prompt HERE, so the pieces stay consistent. A static audit
(tests/test_promptgate.py) fails if any module other than this gate calls
``prompts.build_system_prompt`` / ``build_cli_system`` directly (the specialized
subagent / selfimprove assemblers are explicitly exempt).

Pure standard library. (docs/v2.md #7)
"""

from __future__ import annotations

from typing import Any, Optional

from . import neurosis, persona, presets, prompts
from .moirai import trigger as moirai_trigger


def _filter_tool_guidance(system: str, cfg: dict[str, Any]) -> str:
    disabled = {
        str(name)
        for name in (cfg.get("disabled_tools", []) or [])
    }
    disabled |= presets.deny_tools(cfg.get("model"), cfg)
    egress = cfg.get("egress", {})
    if (isinstance(egress, dict)
            and egress.get("enabled") is True
            and egress.get("enforced") is True):
        disabled.update({"run_shell", "spawn_subagent"})
    if "spawn_subagent" in disabled:
        system = "\n".join(
            line for line in system.splitlines()
            if "spawn_subagent" not in line
        )
    if "run_shell" in disabled:
        system = system.replace(
            "`run_shell`",
            "the available execution tools",
        ).replace(
            "run_shell",
            "the available execution tools",
        )
    return system


def _goal_note() -> str:
    """The persisted session goal, so the model is steered by it, not just billed.

    Imported lazily: ``goals`` pulls in the approval/cron graph, which prompt
    assembly itself has no need for.
    """
    from . import goals
    return goals.prompt_note()


def _persona(persona_text: Optional[str]) -> str:
    # None -> read SOUL.md fresh (REPL/per-turn); "" -> explicitly no persona.
    return persona.read_soul() if persona_text is None else persona_text


def compose_main(cfg: dict[str, Any], *, skills_index: str = "",
                 memory_block: str = "", role: str = "main", extra: str = "",
                 persona_text: Optional[str] = None,
                 harness_block: str = "") -> str:
    """System prompt for the native agent loop (API providers). Persona + tool
    guidance + skills + memory, then the neurosis auto-trigger note."""
    system = _filter_tool_guidance(prompts.build_system_prompt(
        skills_index=skills_index, memory_block=memory_block, role=role,
        extra=extra, persona=_persona(persona_text),
        harness_block=harness_block
    ), cfg) + presets.role_overlay(cfg.get("model"), cfg) \
        + presets.tool_policy_overlay(
            cfg.get("model"), cfg, surface="native"
        ) \
        + neurosis.auto_trigger_note(cfg) \
        + moirai_trigger.auto_trigger_note(cfg) \
        + _goal_note()
    from . import ide
    return prompts.seal_research_policy(system) + ide.consume_context_note()


def compose_cli(cfg: dict[str, Any], *, memory_block: str = "",
                preloaded: Optional[list[str]] = None, extra: str = "",
                persona_text: Optional[str] = None,
                harness_block: str = "") -> str:
    """System prompt for CLI-agent backends (Claude Code / Codex). ``extra`` is
    appended before the neurosis note (e.g. the gateway's skills-index block)."""
    sysp = _filter_tool_guidance(prompts.build_cli_system(
        memory_block=memory_block, preloaded=preloaded,
        persona=_persona(persona_text), harness_block=harness_block), cfg)
    if extra:
        sysp += extra
    system = sysp + presets.role_overlay(cfg.get("model"), cfg) \
        + presets.tool_policy_overlay(
            cfg.get("model"), cfg, surface="cli"
        ) \
        + neurosis.auto_trigger_note(cfg) \
        + moirai_trigger.auto_trigger_note(cfg) \
        + _goal_note()
    from . import ide
    return prompts.seal_research_policy(system) + ide.consume_context_note()


def compose_subagent(cfg: dict[str, Any], *, skills_index: str = "",
                     preloaded: Optional[list[tuple[str, str]]] = None) -> str:
    """System prompt for a native subagent using its effective model preset."""
    system = prompts.build_system_prompt(
        skills_index=skills_index,
        role="subagent",
        preloaded=preloaded,
    )
    system += presets.role_overlay(cfg.get("model"), cfg)
    system += presets.tool_policy_overlay(
        cfg.get("model"), cfg, surface="native"
    )
    return prompts.seal_research_policy(system)
