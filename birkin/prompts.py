"""System-prompt construction.

Kept in one place so the main agent and subagents stay consistent. The prompt
follows progressive disclosure: the model gets a compact *skill index* and is
told to ``load_skill`` for details, rather than being flooded with every
skill's full text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# Optional layered prompt files composed from the workspace (cwd), if present —
# identity/policy/tool notes, like hermes' SOUL/AGENTS/TOOLS.
_WORKSPACE_PROMPT_FILES = ("SOUL.md", "AGENTS.md", "TOOLS.md")


def workspace_prompt_block() -> str:
    parts: list[str] = []
    for name in _WORKSPACE_PROMPT_FILES:
        path = Path.cwd() / name
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if text:
                parts.append(f"## {name}\n{text}")
    return "\n\n".join(parts)

_IDENTITY = """You are birkin — a warm, sharp personal agent that genuinely \
remembers the people you work with.

You operate in a real workspace with file, shell, and web tools, and you can \
delegate focused sub-tasks to isolated subagents. Talk like a thoughtful friend \
who happens to be an expert: warm, natural, and human — never stiff or robotic. \
Prefer being genuinely useful over being verbose, admit uncertainty plainly \
instead of bluffing, and verify your work before claiming success. Use what you \
remember about the person to make replies feel personal, not generic."""

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
                        preloaded: Optional[list[tuple[str, str]]] = None,
                        persona: str = "") -> str:
    # The user's SOUL.md persona (when set) replaces the default identity slot;
    # everything else (tool guidance, skills, memory) is appended as usual.
    identity = persona.strip() if persona and persona.strip() else _IDENTITY
    parts: list[str] = [identity]

    if role == "subagent":
        parts.append(
            "You are running as a SUBAGENT: you cannot see the parent "
            "conversation. Complete the given task fully and return a clear, "
            "self-contained result.")

    workspace = workspace_prompt_block()
    if workspace:
        parts.append(workspace)

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


_CLI_IDENTITY = """You are birkin, a helpful, concise agent. You are running on \
top of your own local agent CLI, which already has file, shell, and web tools — \
use them yourself to read files, run commands, fetch pages, and run any scripts \
referenced below. Be direct and act; don't just describe. Format answers in \
clear, compact Markdown (short paragraphs, bullets, code blocks). Never fabricate \
results — verify with your tools."""


def build_cli_system(*, memory_block: str = "",
                     preloaded: Optional[list[str]] = None,
                     persona: str = "") -> str:
    """A concise prompt for CLI-agent backends (Claude Code / Codex).

    Those backends can't call birkin's tools, so instead of the tool-loop
    guidance we inject birkin's identity, memory, and any skills routed as
    relevant to the request (full text, including bundled-script paths the CLI
    can run with its own shell). The user's SOUL.md persona (when set) replaces
    the default voice."""
    identity = persona.strip() if persona and persona.strip() else _CLI_IDENTITY
    parts: list[str] = [identity]
    workspace = workspace_prompt_block()
    if workspace:
        parts.append(workspace)
    if memory_block:
        parts.append("## What you know about the user (birkin memory)\n"
                     + memory_block)
    if preloaded:
        parts.append("## Relevant skills — follow these if they apply\n\n"
                     + "\n\n---\n\n".join(preloaded))
    return "\n\n".join(parts)
