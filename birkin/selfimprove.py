"""Self-improvement: turn session experience into durable skills and memory.

After a task, ``reflect_and_learn`` runs a small, tool-restricted agent over a
transcript. It is instructed to:
- call ``create_skill`` when it spots a reusable, generalizable procedure,
- call ``remember`` for durable facts about the user/project,
- otherwise report that nothing is worth saving.

This is the same "nudge itself to persist knowledge" idea as hermes, kept
opt-in and cheap (a single short agent run).
"""

from __future__ import annotations

from typing import Any

from . import prompts
from .agent import Agent
from .tools import ToolContext, build_registry

_REFLECTION = """## Your job right now
You are birkin's self-improvement pass. Review the transcript below and persist \
anything durably useful:
- If it contains a reusable, generalizable procedure (not a one-off), call \
create_skill ONCE with a clear kebab-case name, a one-line description, and \
concise markdown instructions (include 'When to Use' / 'When NOT to Use').
- If it reveals stable facts about the user or project, call remember.
- Do not save secrets, one-off trivia, or things already covered by an existing \
skill (check the catalog first).
After acting, reply with a one-line summary of what you saved, or "Nothing new \
worth saving."."""


def transcript_from_messages(messages: list[dict[str, Any]], limit: int = 40) -> str:
    """Flatten canonical content-block messages into readable text."""
    out: list[str] = []
    for m in messages[-limit:]:
        role = m.get("role", "?")
        blocks = m.get("content", [])
        if isinstance(blocks, str):
            out.append(f"[{role}] {blocks}")
            continue
        for b in blocks:
            t = b.get("type")
            if t == "text":
                out.append(f"[{role}] {b.get('text', '')}")
            elif t == "tool_use":
                out.append(f"[{role}->tool] {b.get('name')}({b.get('input')})")
            elif t == "tool_result":
                content = b.get("content", "")
                if isinstance(content, list):
                    content = " ".join(str(c) for c in content)
                out.append(f"[tool_result] {str(content)[:500]}")
    return "\n".join(out)


def reflect_and_learn(ctx: ToolContext, transcript: str) -> str:
    if not ctx.cfg.get("self_improve", True):
        return "Self-improvement is disabled in config."
    if not transcript.strip():
        return "Nothing to reflect on."

    skills_index = ctx.skills.index() if ctx.skills else ""
    system = prompts.build_system_prompt(
        skills_index=skills_index, role="main", extra=_REFLECTION)
    registry = build_registry(ctx, include={"skills", "memory"})
    agent = Agent(client=ctx.client, system=system, registry=registry,
                  max_turns=6, model=ctx.cfg.get("model"))
    return agent.run("Transcript to learn from:\n\n" + transcript)
