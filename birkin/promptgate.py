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

from . import neurosis, persona, prompts


def _persona(persona_text: Optional[str]) -> str:
    # None -> read SOUL.md fresh (REPL/per-turn); "" -> explicitly no persona.
    return persona.read_soul() if persona_text is None else persona_text


def compose_main(cfg: dict[str, Any], *, skills_index: str = "",
                 memory_block: str = "", role: str = "main", extra: str = "",
                 persona_text: Optional[str] = None) -> str:
    """System prompt for the native agent loop (API providers). Persona + tool
    guidance + skills + memory, then the neurosis auto-trigger note."""
    return prompts.build_system_prompt(
        skills_index=skills_index, memory_block=memory_block, role=role,
        extra=extra, persona=_persona(persona_text)
    ) + neurosis.auto_trigger_note(cfg)


def compose_cli(cfg: dict[str, Any], *, memory_block: str = "",
                preloaded: Optional[list[str]] = None, extra: str = "",
                persona_text: Optional[str] = None) -> str:
    """System prompt for CLI-agent backends (Claude Code / Codex). ``extra`` is
    appended before the neurosis note (e.g. the gateway's skills-index block)."""
    sysp = prompts.build_cli_system(
        memory_block=memory_block, preloaded=preloaded,
        persona=_persona(persona_text))
    if extra:
        sysp += extra
    return sysp + neurosis.auto_trigger_note(cfg)
