"""System-prompt construction.

Kept in one place so the main agent and subagents stay consistent. The prompt
follows progressive disclosure: the model gets a compact *skill index* and is
told to ``load_skill`` for details, rather than being flooded with every
skill's full text.
"""

from __future__ import annotations

from typing import Any, Optional

_IDENTITY = """You are birkin, a lightweight, self-improving CLI agent.

You operate in a real workspace with file, shell, and web tools, and you can \
delegate focused sub-tasks to isolated subagents. Be concise, act decisively, \
and verify your work before claiming success."""

_TOOL_GUIDANCE = """## Working principles
- Prefer doing over describing: use tools to inspect and change the workspace.
- Load a skill (load_skill) whenever a cataloged skill matches the task.
- Delegate large, self-contained, or parallelizable work to spawn_subagent so \
this conversation stays focused. Give subagents a complete brief.
- If you discover a reusable procedure, call create_skill so it persists. \
Refine an existing skill with improve_skill.
- Record durable facts about the user or project with the remember tool.
- Never fabricate results. If unsure, say so and investigate."""


def build_system_prompt(*, skills_index: str = "", memory_block: str = "",
                        role: str = "main", extra: str = "",
                        preloaded: Optional[list[tuple[str, str]]] = None) -> str:
    parts: list[str] = [_IDENTITY]

    if role == "subagent":
        parts.append(
            "You are running as a SUBAGENT: you cannot see the parent "
            "conversation. Complete the given task fully and return a clear, "
            "self-contained result.")

    parts.append(_TOOL_GUIDANCE)

    if skills_index:
        parts.append("## Available skills (call load_skill for full instructions)\n"
                     + skills_index)

    if preloaded:
        blocks = [f"### {name}\n{body}" for name, body in preloaded]
        parts.append("## Preloaded skills\n" + "\n\n".join(blocks))

    if memory_block:
        parts.append("## What you know about the user\n" + memory_block)

    if extra:
        parts.append(extra)

    return "\n\n".join(parts)
