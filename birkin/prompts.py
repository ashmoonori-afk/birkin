"""System-prompt construction.

Kept in one place so the main agent and subagents stay consistent. The prompt
follows progressive disclosure: the model gets a compact *skill index* and is
told to ``load_skill`` for details, rather than being flooded with every
skill's full text.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from . import local_environment_policy

# Optional layered prompt files composed from the workspace (cwd), if present —
# identity/policy/tool notes, like hermes' SOUL/AGENTS/TOOLS.
_WORKSPACE_PROMPT_FILES = ("AGENTS.md", "TOOLS.md")
_DEPRECATED_WORKSPACE_SOUL_NOTICES: set[Path] = set()


def _notice_deprecated_workspace_soul() -> None:
    path = (Path.cwd() / "SOUL.md").resolve()
    if path in _DEPRECATED_WORKSPACE_SOUL_NOTICES or not path.is_file():
        return
    _DEPRECATED_WORKSPACE_SOUL_NOTICES.add(path)
    print(
        "[birkin] workspace SOUL.md is deprecated; use AGENTS.md for "
        "workspace instructions or ~/.birkin/SOUL.md for persona.",
        file=sys.stderr,
        flush=True,
    )


def workspace_prompt_block() -> str:
    _notice_deprecated_workspace_soul()
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
- Before a multi-step task or a slow tool call, first say in ONE short sentence \
what you're about to do, so the user sees your intent immediately instead of \
waiting in silence. One line — don't narrate every step.
- Prefer doing over describing: use tools to inspect and change the workspace.
- Load a skill (load_skill) whenever a cataloged skill matches the task.
- Delegate large, self-contained, or parallelizable work to spawn_subagent so \
this conversation stays focused. Give subagents a complete brief.
- If you discover a reusable procedure, call create_skill so it persists. \
Refine an existing skill with improve_skill.
- Record durable facts about the user or project with the remember tool.
- Never fabricate results. If unsure, say so and investigate."""

UI_COMPONENT_POLICY_OPEN = "<ui-component-policy>"
UI_COMPONENT_POLICY_CLOSE = "</ui-component-policy>"
UI_COMPONENT_POLICY = (
    f"{UI_COMPONENT_POLICY_OPEN}\n"
    "For frontend and web UI design or implementation:\n"
    "- Use shadcn/ui (https://ui.shadcn.com/docs/components) as the default "
    "component book unless the user or workspace specifies another design "
    "system.\n"
    "- Prefer its established component composition, interaction, state, and "
    "accessibility patterns before inventing custom controls.\n"
    "- In a compatible React and Tailwind project, use or adapt the actual "
    "components. For standalone HTML or another stack, translate the relevant "
    "structure and behavior without pretending shadcn/ui is an installed "
    "dependency.\n"
    "- Preserve the product's own visual identity; shadcn/ui is the component "
    "reference, not a requirement to copy its default theme.\n"
    f"{UI_COMPONENT_POLICY_CLOSE}"
)

RESEARCH_EVIDENCE_OPEN = "<research-evidence-policy>"
RESEARCH_EVIDENCE_CLOSE = "</research-evidence-policy>"
RESEARCH_EVIDENCE_POLICY = (
    f"{RESEARCH_EVIDENCE_OPEN}\n"
    "Whenever an answer relies on internet research:\n"
    "- Treat search snippets, result titles, and remembered facts as discovery "
    "only. Open the exact source page before using it as evidence.\n"
    "- Prefer the closest primary source: official documentation, regulator or "
    "government data, an original study, a first-party announcement, or the "
    "dataset itself. Clearly label analysis or inference as such.\n"
    "- For current, recent, latest, or version-sensitive claims, inspect the "
    "source's publication, updated, effective, version, or as-of date and "
    "compare it with the retrieved date. Search rank is not proof of recency. "
    "If no source date is available, say that recency is unverified and do not "
    "call the information latest.\n"
    "- Cross-check important or time-sensitive claims with a second independent "
    "authoritative source when reasonably available. If only one source exists "
    "or sources conflict, disclose that limitation and the conflict.\n"
    "- End with a Sources section mapping every material web-derived claim to "
    "its exact URL, source title or organization, publication/updated date (or "
    "'date unavailable'), and retrieved date. Never cite a search-results page "
    "as the supporting source.\n"
    "- If the available evidence cannot establish the requested fact or its "
    "recency, say so instead of guessing.\n"
    f"{RESEARCH_EVIDENCE_CLOSE}"
)


def seal_research_policy(system_prompt: str) -> str:
    """Keep one authoritative research contract after all other prompt text."""
    without_policy = system_prompt.replace(
        RESEARCH_EVIDENCE_POLICY, ""
    ).strip()
    if not without_policy:
        return RESEARCH_EVIDENCE_POLICY
    return f"{without_policy}\n\n{RESEARCH_EVIDENCE_POLICY}"


def build_system_prompt(*, skills_index: str = "", memory_block: str = "",
                        role: str = "main", extra: str = "",
                        preloaded: Optional[list[tuple[str, str]]] = None,
                        persona: str = "", profile_block: str = "",
                        harness_block: str = "") -> str:
    # The user's SOUL.md persona (when set) replaces the default identity slot;
    # everything else (tool guidance, skills, memory) is appended as usual.
    clean = local_environment_policy.strip_markers
    identity_text = clean(persona.strip()) if persona else ""
    identity = identity_text or _IDENTITY
    parts: list[str] = [identity]
    if profile_block:
        parts.append(clean(profile_block))

    if role == "subagent":
        parts.append(
            "You are running as a SUBAGENT: you cannot see the parent "
            "conversation. Complete the given task fully and return a clear, "
            "self-contained result.")

    workspace = clean(workspace_prompt_block())
    if workspace:
        parts.append(workspace)

    parts.append(_TOOL_GUIDANCE)

    if skills_index:
        parts.append("## Available skills (call load_skill for full instructions)\n"
                     + clean(skills_index))

    if preloaded:
        blocks = [f"### {name}\n{clean(body)}" for name, body in preloaded]
        parts.append("## Preloaded skills\n" + "\n\n".join(blocks))

    if memory_block:
        parts.append("## What you know about the user\n" + clean(memory_block))

    if harness_block:
        parts.append(clean(harness_block))

    if extra:
        parts.append(clean(extra))

    parts.append(local_environment_policy.render())
    parts.append(UI_COMPONENT_POLICY)
    parts.append(RESEARCH_EVIDENCE_POLICY)
    return "\n\n".join(parts)


_CLI_IDENTITY = """You are birkin, a helpful, concise agent. You are running on \
top of your own local agent CLI, which already has file, shell, and web tools — \
use them yourself to read files, run commands, fetch pages, and run any scripts \
referenced below. Be direct and act; don't just describe. Format answers in \
clear, compact Markdown (short paragraphs, bullets, code blocks). Never fabricate \
results — verify with your tools."""


def cli_mcp_block() -> str:
    """Tell a CLI backend that birkin's own tools are attached, and findable.

    codex 0.145 does not list MCP tools upfront — they surface through
    tool_search_tool. Probed with morpheus's exact flags, "list your
    tools" returned 20 codex built-ins and zero birkin ones, while
    "search for memory_write_note" found it every time. Without this note the
    model concludes the tools do not exist and writes prose about what it
    WOULD have saved: three consecutive nightly runs recorded proposals=[]
    that way, and a tracking cron job reported "no previous record" on both
    of its runs while holding memory_write_note.

    Deliberately does not enumerate the twelve tools: there is no public
    listing API to derive them from, so a hardcoded list would drift into a
    lie. Naming the server and the three capability groups is enough for the
    model to search.
    """
    from .mcp_server import _SERVER_NAME
    return (
        f"\n\n## Your birkin tools (MCP server `{_SERVER_NAME}`)\n"
        "birkin has attached its own tool server to you: memory (search, read, "
        "write, link, rezone), skills (list, load, create, improve), and "
        "propose_action for anything that needs the user's approval.\n"
        "Your client may NOT list them upfront. If you do not see them, call "
        "tool_search_tool to surface them BEFORE concluding they are absent.\n"
        "Use them. On an unattended run what you write through these tools is "
        "the only thing that survives — a reply saying you had no tools, or "
        "describing what you would have saved, is a lost run.\n")


def build_cli_system(*, memory_block: str = "",
                     preloaded: Optional[list[str]] = None,
                     persona: str = "", profile_block: str = "",
                     harness_block: str = "") -> str:
    """A concise prompt for CLI-agent backends (Claude Code / Codex).

    These backends run their own tool loop, so instead of birkin's tool-loop
    guidance we inject birkin's identity, memory, and any skills routed as
    relevant to the request (full text, including bundled-script paths the CLI
    can run with its own shell). The user's SOUL.md persona (when set) replaces
    the default voice.

    They CAN call birkin's own tools when the MCP server is attached — see
    :func:`cli_mcp_block`, which the caller appends via ``extra``. This
    docstring used to claim the opposite, and that belief is why unattended
    runs kept reporting they had no tools while holding twelve of them."""
    clean = local_environment_policy.strip_markers
    identity_text = clean(persona.strip()) if persona else ""
    identity = identity_text or _CLI_IDENTITY
    parts: list[str] = [identity]
    if profile_block:
        parts.append(clean(profile_block))
    workspace = clean(workspace_prompt_block())
    if workspace:
        parts.append(workspace)
    if memory_block:
        parts.append("## What you know about the user (birkin memory)\n"
                     + clean(memory_block))
    if harness_block:
        parts.append(clean(harness_block))
    if preloaded:
        parts.append("## Relevant skills — follow these if they apply\n\n"
                     + "\n\n---\n\n".join(clean(body) for body in preloaded))
    parts.append(local_environment_policy.render())
    parts.append(UI_COMPONENT_POLICY)
    parts.append(RESEARCH_EVIDENCE_POLICY)
    return "\n\n".join(parts)
