"""Summonable specialist agents: a named roster on top of subagents.

``spawn_subagent`` delegates to an anonymous helper that must be briefed from
scratch every time. A *summoned* agent is a named specialist — "researcher",
"sheet-analyst", "meeting-scribe" — with its own instructions, a least-privilege
tool scope, preloaded skills, and a turn budget, so the user (``/summon``,
``birkin summon``) or the main agent (``spawn_subagent`` with ``agent``) can hand
work to the right expert by name.

The roster has two sources:

- **built-in** specialists defined here, tuned for office work;
- **user** specialists in ``BIRKIN_HOME/agents/<name>.md`` (frontmatter + body).
  They add new names only: a built-in name always means the built-in, so a
  planted file cannot pass itself off as a trusted specialist. The native file
  tools cannot write this directory (``tools/files.py`` control dirs).

A summoned agent is still a subagent: it runs through ``run_subagent`` with the
same depth limit, tree budget, approval gating, and tool policy (disabled
tools, model presets, egress enforcement). Its tool scope can only narrow the
policy, never widen it, and it cannot summon further agents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import config
from .skills import frontmatter

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
# A model id reaches CLI argv; a leading "-" would be parsed as a flag.
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,99}$")
MAX_FILE_BYTES = 64 * 1024
MAX_INSTRUCTIONS_CHARS = 16_000
MAX_TITLE_CHARS = 60
MAX_DESCRIPTION_CHARS = 300
MAX_SKILLS = 4
MIN_TURNS, MAX_TURNS, DEFAULT_TURNS = 1, 40, 12

# Tool groups a specialist may request. ``subagent`` is excluded on purpose:
# summoned agents are leaves, so one summon cannot fan out into a tree.
ALLOWED_TOOL_GROUPS = frozenset({
    "files", "web", "documents", "research", "connections", "sessions",
    "vision", "skills", "browser", "shell", "desktop", "plugins", "egress",
    "worker", "companion",
})

_SHARED_RULES = (
    "Work only on the task you were given; you cannot see the parent "
    "conversation, so state any assumption you had to make. Never fabricate "
    "facts, figures, file contents, or sources. Consequential actions (writing "
    "or sending anything outside the workspace, Office changes, mail, calendar) "
    "go through Birkin's approval requests — never try to bypass them; report "
    "the request id instead. Lead the final result with the conclusion, then "
    "the key evidence (file paths, sheet/cell ranges, URLs), then open "
    "questions. Write the result in the language of the task."
)


class SummonError(ValueError):
    """A summon request or agent definition was rejected."""


class AgentDefinitionError(SummonError):
    """The named agent has a definition file, but it failed validation."""

    def __init__(self, name: str, reason: str):
        super().__init__(f"agent definition {name!r} is invalid: {reason}")
        self.name = name
        self.reason = reason


@dataclass(frozen=True)
class AgentSpec:
    """One summonable specialist."""

    name: str
    title: str
    description: str
    instructions: str
    tools: tuple[str, ...]
    skills: tuple[str, ...] = ()
    max_turns: int = DEFAULT_TURNS
    model: str = ""
    source: str = "builtin"
    path: Optional[Path] = field(default=None, compare=False)

    def system_block(self) -> str:
        """The role overlay appended to the subagent system prompt."""
        return (
            f"## Your role: {self.name} ({self.title})\n"
            f"{self.instructions.strip()}\n\n{_SHARED_RULES}"
        )

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "tools": list(self.tools),
            "skills": list(self.skills),
            "max_turns": self.max_turns,
            "model": self.model,
            "source": self.source,
        }


BUILTIN_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec(
        name="researcher",
        title="리서처",
        description="공개 자료를 조사하고 출처·날짜와 함께 근거를 정리합니다.",
        instructions=(
            "You are a research specialist. Find primary sources, open them "
            "before citing, record publication dates, separate sourced claims "
            "from inference, and flag conflicts or unverified recency."
        ),
        tools=("web", "research", "files"),
        skills=("web-research", "fact-checking"),
        max_turns=16,
    ),
    AgentSpec(
        name="doc-analyst",
        title="문서 분석가",
        description="DOCX·PPTX·PDF·HWPX 문서를 검사·추출·비교하고 핵심을 요약합니다.",
        instructions=(
            "You are an Office document analyst. Import local files with "
            "local_document_import before inspecting, inspect before you "
            "extract, use Birkin's registered document tools "
            "(inspect_document, extract_document, compare_documents), quote "
            "the exact location of every finding, and never modify the "
            "source document."
        ),
        tools=("documents", "files"),
        skills=("office-work-os",),
    ),
    AgentSpec(
        name="sheet-analyst",
        title="스프레드시트 분석가",
        description="XLSX·CSV 데이터를 분석하고 수치를 검증해 표와 함께 보고합니다.",
        instructions=(
            "You are a spreadsheet analyst. Import local files with "
            "local_document_import before inspecting, use analyze_workbook and "
            "extract_document, cite sheet names and cell ranges for every "
            "number, recompute totals you report, and call out missing, "
            "hidden, or inconsistent data instead of guessing."
        ),
        tools=("documents", "files"),
        skills=("spreadsheets",),
    ),
    AgentSpec(
        name="meeting-scribe",
        title="회의록 정리 담당",
        description="회의 메모나 녹취에서 결정 사항·할 일·담당자·기한을 뽑아 정리합니다.",
        instructions=(
            "You turn meeting material into decisions, action items, owners, "
            "and due dates. Import local files with local_document_import "
            "before inspecting, use review_meeting_actions for documents, keep "
            "each action verifiable, mark unknown owners or dates as unknown, "
            "and propose follow-up work items only through work_item_request."
        ),
        tools=("documents", "files"),
        skills=("meeting-notes",),
        max_turns=10,
    ),
    AgentSpec(
        name="report-writer",
        title="보고서 작성가",
        description="조사·분석 결과를 보고서·요약본·발표 초안으로 구성합니다.",
        instructions=(
            "You draft reports, briefs, and presentation outlines from the "
            "material you are given or can read. Structure conclusion-first, "
            "keep every figure traceable to its source, and create or change "
            "Office files only through office_job_request so the user can "
            "review the change before it is written."
        ),
        tools=("documents", "files", "web"),
        skills=("word-documents",),
        max_turns=14,
    ),
    AgentSpec(
        name="planner",
        title="업무 계획가",
        description="목표를 단계·담당·일정·위험으로 나눠 실행 계획과 후속 작업을 제안합니다.",
        instructions=(
            "You plan work. Break the goal into ordered, owned, measurable "
            "steps with dates and risks, check existing follow-ups with "
            "list_work_items, and propose new ones only through "
            "work_item_request."
        ),
        tools=("documents", "files"),
        skills=("task-breakdown", "planning"),
        max_turns=10,
    ),
    AgentSpec(
        name="mail-drafter",
        title="메일 초안 작성가",
        description="받은 메일과 맥락을 읽고 답장·안내 메일 초안을 작성합니다(발송은 승인 후).",
        instructions=(
            "You draft email. Read the thread or context first, match the "
            "recipient's register, keep the draft short and specific, and "
            "save it with m365_mail_draft when Microsoft 365 is connected. "
            "Sending always requires the user's approval; never claim a "
            "message was sent."
        ),
        tools=("connections", "files"),
        skills=("email-draft",),
        max_turns=10,
    ),
)


def agents_dir() -> Path:
    """User-defined agent definitions live in ``BIRKIN_HOME/agents``."""
    return config.birkin_home() / "agents"


def _text(meta: dict[str, Any], key: str, limit: int, default: str = "") -> str:
    value = meta.get(key, default)
    if value is None:
        value = default
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise SummonError(f"{key} must be a string")
    text = " ".join(str(value).split())
    if len(text) > limit:
        raise SummonError(f"{key} exceeds {limit} characters")
    return text


def _names(meta: dict[str, Any], key: str) -> tuple[str, ...]:
    raw = meta.get(key, [])
    if raw in (None, ""):
        return ()
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
        raise SummonError(f"{key} must be a list of names")
    seen: list[str] = []
    for value in raw:
        name = value.strip()
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def parse_definition(text: str, *, stem: str, path: Optional[Path] = None
                     ) -> AgentSpec:
    """Validate one ``agents/<stem>.md`` file into an :class:`AgentSpec`."""
    meta, body = frontmatter.parse(text)
    name = _text(meta, "name", 32, stem) or stem
    if name != stem:
        raise SummonError("name must match the file name")
    if not NAME_RE.fullmatch(name):
        raise SummonError("name must be 2-32 lowercase letters, digits, or '-'")
    description = _text(meta, "description", MAX_DESCRIPTION_CHARS)
    if not description:
        raise SummonError("description is required")
    title = _text(meta, "title", MAX_TITLE_CHARS, name) or name
    instructions = body.strip()
    if not instructions:
        raise SummonError("instructions (the markdown body) are required")
    if len(instructions) > MAX_INSTRUCTIONS_CHARS:
        raise SummonError(
            f"instructions exceed {MAX_INSTRUCTIONS_CHARS} characters")
    tools = _names(meta, "tools")
    if not tools:
        raise SummonError("tools must name at least one tool group")
    unknown = [group for group in tools if group not in ALLOWED_TOOL_GROUPS]
    if unknown:
        raise SummonError(f"unsupported tool group: {unknown[0]}")
    skills = _names(meta, "skills")
    if len(skills) > MAX_SKILLS:
        raise SummonError(f"at most {MAX_SKILLS} skills may be preloaded")
    raw_turns = meta.get("max_turns", DEFAULT_TURNS)
    if (isinstance(raw_turns, bool) or not isinstance(raw_turns, int)
            or not MIN_TURNS <= raw_turns <= MAX_TURNS):
        raise SummonError(
            f"max_turns must be an integer from {MIN_TURNS} to {MAX_TURNS}")
    model = _text(meta, "model", 100)
    if model in ("default", "inherit"):
        model = ""
    if model and not MODEL_RE.fullmatch(model):
        raise SummonError("model is not a valid model id")
    return AgentSpec(
        name=name, title=title, description=description,
        instructions=instructions, tools=tools, skills=skills,
        max_turns=raw_turns, model=model, source="user", path=path,
    )


def _read_definition(path: Path) -> str:
    info = path.lstat()
    if not path.is_file() or path.is_symlink():
        raise SummonError("definition must be a regular file")
    if info.st_size > MAX_FILE_BYTES:
        raise SummonError(f"definition exceeds {MAX_FILE_BYTES} bytes")
    return path.read_text(encoding="utf-8", errors="replace")


def load_roster() -> tuple[dict[str, AgentSpec], dict[str, str]]:
    """Return ``(agents by name, rejected definitions by file name)``.

    A broken user file never hides the rest of the roster; it is reported so
    ``/summon`` and ``birkin summon`` can say why it is missing.
    """
    roster = {spec.name: spec for spec in BUILTIN_AGENTS}
    rejected: dict[str, str] = {}
    directory = agents_dir()
    if not directory.is_dir():
        return roster, rejected
    builtin = set(roster)
    for path in sorted(directory.glob("*.md")):
        if path.stem in builtin:
            rejected[path.name] = "name is reserved by a built-in agent"
            continue
        try:
            spec = parse_definition(
                _read_definition(path), stem=path.stem, path=path)
        except (OSError, SummonError) as exc:
            rejected[path.name] = str(exc)
            continue
        roster[spec.name] = spec
    return roster, rejected


def list_agents() -> list[AgentSpec]:
    roster, _rejected = load_roster()
    return sorted(roster.values(), key=lambda spec: spec.name)


def get_agent(name: str) -> AgentSpec:
    roster, rejected = load_roster()
    key = str(name or "").strip().lower().lstrip("@")
    spec = roster.get(key)
    if spec is not None:
        return spec
    reason = rejected.get(f"{key}.md") if key not in roster else None
    if reason:
        raise AgentDefinitionError(key, reason)
    raise SummonError(
        f"unknown agent {key!r}; available: {', '.join(sorted(roster))}")


def roster_brief(limit: int = 1200) -> str:
    """One line per agent, for the ``spawn_subagent`` tool schema."""
    lines: list[str] = []
    size = 0
    for spec in list_agents():
        line = f"{spec.name}: {spec.description}"
        if size + len(line) > limit:
            lines.append("…")
            break
        lines.append(line)
        size += len(line) + 2
    return "; ".join(lines)


class SummonBudgetExceeded(SummonError):
    """The configured token budget refuses a direct summon."""


_DETACHED_RE = re.compile(r"\bDetached subagent ([0-9a-f]{12}) started\b")


def detached_run_id(result: str) -> str:
    """The run id inside ``run_subagent``'s detached acknowledgement, or ""."""
    match = _DETACHED_RE.search(str(result or ""))
    return match.group(1) if match else ""


NO_TEXT_COPY = "결과 텍스트가 없습니다."


def result_text(result: object) -> str:
    """A finished run's result as a person sees it: the text itself, or Korean
    copy for ``run_subagent``'s no-text stand-in or an empty result."""
    from .subagent import NO_TEXT_RESULT  # local: subagent imports tools

    text = str(result or "")
    return NO_TEXT_COPY if text.strip() in ("", NO_TEXT_RESULT) else text


def summon(name: str, task: str, parent_ctx: Any, *, detach: bool = False,
           reserve_tokens: int = 0, reserve_usd: float = 0.0) -> str:
    """Run ``task`` with the named specialist and return its result text.

    This is the direct entry point for ``/summon`` and ``birkin summon``. It
    runs outside a chat turn, so it applies the same token-budget gate a turn
    does; ``run_subagent`` records the spend in the ledger that gate reads.
    """
    from . import budget
    from .subagent import run_subagent  # local: subagent imports tools

    spec = get_agent(name)
    task = str(task or "").strip()
    if not task:
        raise SummonError("task is required")
    over, why = budget.is_over(parent_ctx.cfg)
    if over:
        raise SummonBudgetExceeded(why)
    if getattr(parent_ctx, "tree_budget", None) is not None:
        parent_ctx.tree_budget.begin_tree()  # a direct summon is a new task
    return run_subagent(
        task, parent_ctx,
        skill_names=list(spec.skills), max_turns=spec.max_turns,
        detach=detach, reserve_tokens=reserve_tokens, reserve_usd=reserve_usd,
        specialist=spec,
    )
