"""SkillManager: index skills for the prompt, load them on demand, and let the
agent author/refine its own skills (the self-improvement substrate).

The model sees only a compact *index* (name + one-line description) in its
system prompt. When a skill is relevant it calls ``load_skill`` to pull the
full instructions into context — the same progressive-disclosure pattern used
by hermes and the agentskills standard.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from .. import config, store
from .loader import Skill, discover


class SkillProposalError(RuntimeError):
    pass


class SkillManager:
    def __init__(self, dirs: list[tuple[Path, str]]):
        self._dirs = dirs
        self.skills: dict[str, Skill] = discover(dirs)
        self._sig = self._signature()
        self._checked_at = time.monotonic()
        self._revision = 0

    @property
    def revision(self) -> int:
        return self._revision

    def reload(self) -> None:
        self.skills = discover(self._dirs)
        self._sig = self._signature()
        self._revision += 1

    def _signature(self) -> tuple[tuple[str, float], ...]:
        """Cheap fingerprint (paths + mtimes, no file reads) for hot-reload."""
        items: list[tuple[str, float]] = []
        for base, _src in self._dirs:
            if base and base.is_dir():
                for f in base.rglob("SKILL.md"):
                    try:
                        items.append((str(f), f.stat().st_mtime))
                    except OSError:
                        continue
        return tuple(sorted(items))

    def reload_if_changed(self, debounce: float = 1.0) -> bool:
        """Reload skills if any SKILL.md changed/added/removed since last check.
        Debounced so it's cheap to call before every turn. Returns True if reloaded."""
        now = time.monotonic()
        if now - self._checked_at < debounce:
            return False
        self._checked_at = now
        sig = self._signature()
        if sig != self._sig:
            self.skills = discover(self._dirs)
            self._sig = sig
            self._revision += 1
            return True
        return False

    def get(self, name: str) -> Skill | None:
        if name in self.skills:
            return self.skills[name]
        low = name.lower()
        for n, s in self.skills.items():
            if n.lower() == low:
                return s
        return None

    def eligible_skills(self) -> list[Skill]:
        """Skills whose frontmatter prerequisites are met on this machine."""
        return [s for s in self.skills.values() if s.eligible]

    def index(self) -> str:
        """Compact catalog for the system prompt (eligible skills only)."""
        skills = self.eligible_skills()
        if not skills:
            return "(no skills installed yet)"
        lines = []
        for s in sorted(skills, key=lambda x: x.name):
            desc = s.description or "(no description)"
            lines.append(f"- {s.name}: {desc}")
        return "\n".join(lines)

    def route(self, query: str, limit: int = 3) -> list[Skill]:
        """Pick the most relevant *eligible* skills for a query by keyword overlap
        against name + description + tags + body. Used to inject skills into
        CLI-agent prompts (which can't call load_skill)."""
        terms = [t for t in re.findall(r"[^\W_]+", (query or "").lower())
                 if len(t) > 2 or (len(t) > 1 and not t.isascii())]
        skills = self.eligible_skills()
        if not terms or not skills:
            return []

        def matched_terms(text: str) -> list[str]:
            tokens = re.findall(r"[^\W_]+", text.lower())
            token_set = set(tokens)
            return [term for term in terms if (
                term in token_set if term.isascii()
                else any(term in token or token in term
                         for token in tokens if len(token) > 1)
            )]

        metadata_scored: list[tuple[int, int, int, Skill]] = []
        for s in skills:
            hay = f"{s.name} {s.description} {' '.join(s.tags)}".lower()
            metadata_terms = matched_terms(hay)
            if metadata_terms:
                metadata_scored.append(
                    (max(len(t) for t in metadata_terms),
                     sum(len(t) for t in metadata_terms),
                     len(metadata_terms), s))
        if metadata_scored:
            metadata_scored.sort(
                key=lambda x: (x[0], x[1], x[2]), reverse=True)
            return [s for _, _, _, s in metadata_scored[:limit]]
        body_scored = []
        for s in skills:
            body_hits = len(matched_terms(s.body()))
            if body_hits:
                body_scored.append((body_hits, s))
        body_scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in body_scored[:limit]]

    def render_skill(self, skill: Skill) -> str:
        """Full skill text plus its bundled files + directory (for execution)."""
        directory = skill.directory.resolve()
        out = (f"# Skill: {skill.name}\n\n"
               f"Skill directory: `{directory}`\n\n{skill.body()}")
        extras = _bundled_files(directory)
        if extras:
            listing = "\n".join(f"- {p}" for p in extras)
            out += (f"\n\n## Bundled files (in this skill's directory)\n"
                    f"{listing}\n\n"
                    f"To run a bundled script, run it with the skill directory "
                    f"as the working directory (e.g. `python scripts/<name>.py ...`).")
        return out

    # -- tools -------------------------------------------------------------

    def tools(self, origin: str = "agent"):
        from ..tools import Tool, ToolContext, ToolResult

        def load_skill(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            self.reload_if_changed(debounce=0.0)
            name = inp.get("name", "").strip()
            skill = self.get(name)
            if not skill:
                avail = ", ".join(sorted(self.skills)) or "(none)"
                return ToolResult(f"No skill named {name!r}. Available: {avail}",
                                  is_error=True)
            from ..curator import record_use
            record_use(skill.name)   # usage feeds the curator lifecycle
            return ToolResult(self.render_skill(skill))

        def create_skill(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            if not ctx.cfg.get("self_improve", True):
                return ToolResult("Self-improvement is disabled in config.",
                                  is_error=True)
            name = inp.get("name", "").strip()
            desc = inp.get("description", "").strip()
            body = inp.get("body", "").strip()
            if not (name and desc and body):
                return ToolResult("create_skill needs name, description, body.",
                                  is_error=True)
            canonical = _slug(name)
            if _skill_exists(canonical):
                return ToolResult(
                    f"Skill {canonical!r} already exists; use improve_skill.",
                    is_error=True)
            # Skill-PR: route through the approval gate so every authoring is
            # recorded. With `skills` in auto_approve (default), it's applied
            # immediately; otherwise it queues for `birkin review`.
            from .. import approvals
            res = approvals.propose(
                category="skill",
                title=f"new skill: {name}",
                description=desc,
                payload={"action": "create", "name": name, "description": desc,
                         "body": body, "tags": inp.get("tags") or []},
                cfg=ctx.cfg, origin=origin)
            if res.get("auto"):
                if not res.get("ok"):
                    return ToolResult(
                        f"Could not create skill {canonical!r}: "
                        f"{res.get('result', 'unknown error')}", is_error=True)
                self.reload()
                return ToolResult(f"Created skill {name!r} (auto-approved).")
            return ToolResult(
                f"Skill proposal recorded for {name!r} — awaiting approval "
                f"(id {res.get('id')}). Run `birkin review` to apply.")

        def improve_skill(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            if not ctx.cfg.get("self_improve", True):
                return ToolResult("Self-improvement is disabled in config.",
                                  is_error=True)
            name = inp.get("name", "").strip()
            addition = inp.get("addition", "").strip()
            skill = self.get(name)
            if not skill:
                return ToolResult(f"No skill named {name!r}.", is_error=True)
            if not addition:
                return ToolResult("improve_skill needs 'addition'.", is_error=True)
            # Skill-PR: route through the approval gate (no silent in-place edits).
            from .. import approvals
            res = approvals.propose(
                category="skill",
                title=f"improve skill: {name}",
                description=addition[:160],
                payload={"action": "improve", "target": skill.name,
                         "addition": addition},
                cfg=ctx.cfg, origin=origin)
            if res.get("auto"):
                if not res.get("ok"):
                    return ToolResult(
                        f"Could not improve skill {name!r}: "
                        f"{res.get('result', 'unknown error')}", is_error=True)
                self.reload()
                return ToolResult(f"Appended a learned note to {name!r} (auto-approved).")
            return ToolResult(
                f"Improvement proposal recorded for {name!r} — awaiting "
                f"approval (id {res.get('id')}). Run `birkin review` to apply.")

        return [
            Tool(
                name="load_skill",
                description="Load the full instructions for a named skill from "
                            "the catalog. Call this whenever a listed skill is "
                            "relevant to the task.",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                fn=load_skill,
            ),
            Tool(
                name="create_skill",
                description="Author a NEW reusable skill from what you just "
                            "learned, so it persists for future sessions. Use "
                            "after solving a non-trivial, repeatable task.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "kebab-case name"},
                        "description": {"type": "string",
                                        "description": "One line; when to use it"},
                        "body": {"type": "string",
                                 "description": "Markdown instructions"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name", "description", "body"],
                },
                fn=create_skill,
            ),
            Tool(
                name="improve_skill",
                description="Append a 'Learned' note to an existing skill to "
                            "refine it based on new experience.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "addition": {"type": "string"},
                    },
                    "required": ["name", "addition"],
                },
                fn=improve_skill,
            ),
        ]


def _guard_agent_written(
    path: Path,
    what: str,
    previous: bytes | None = None,
) -> None:
    """Scan a skill the agent just wrote, rolling the write back if it trips.

    Opt-in (``skills_guard_agent_created``) for the same reason hermes leaves
    it off: on the native loop the agent already has shell, so this catches a
    model that copied something hostile into a skill, not a determined agent.
    """
    if not config.load_config().get("skills_guard_agent_created"):
        return
    from . import guard
    result = guard.scan_skill(path.parent, source="agent-created")
    if guard.should_allow_install(result) is True:
        return
    if previous is None:
        try:
            path.unlink()
        except OSError:
            pass
    else:
        path.write_bytes(previous)
    raise SkillProposalError(
        f"{what} was rolled back — the security scan returned "
        f"{result.verdict}:\n{guard.format_report(result, path.parent.name)}")


def apply_skill_proposal(payload: dict[str, Any]) -> str:
    """Carry out an approved skill change (create / improve). Returns a human
    summary. Used by ``approvals.execute_action(category="skill")``."""
    action = (payload or {}).get("action")
    from ..persistence_safety import unsafe_persistence_reason
    unsafe = unsafe_persistence_reason(
        payload.get("name"), payload.get("description"),
        payload.get("body"), payload.get("addition"))
    if unsafe:
        raise SkillProposalError(unsafe)
    if action == "create":
        name = payload.get("name", "").strip()
        desc = payload.get("description", "").strip()
        body = payload.get("body", "").strip()
        if not (name and desc and body):
            raise SkillProposalError(
                "skill create proposal missing name/description/body")
        canonical = _slug(name)
        path = _user_skill_path(canonical)
        try:
            with store.file_lock(path):
                if _skill_exists(canonical):
                    raise SkillProposalError(f"skill already exists: {canonical}")
                path = _write_skill(name, desc, body, payload.get("tags") or [])
        except store.FileLockTimeout:
            raise SkillProposalError("skill store is busy") from None
        _guard_agent_written(path, f"skill {name!r}")
        return f"Created skill {name!r} at {path}"
    if action == "improve":
        target_name = payload.get("target", "").strip()
        addition = payload.get("addition", "").strip()
        if not (target_name and addition):
            raise SkillProposalError(
                "skill improve proposal missing target/addition")
        lock_path = _user_skill_path(_slug(target_name))
        try:
            with store.file_lock(lock_path):
                dirs = config.skill_dirs(config.load_config())
                skill = discover(dirs).get(target_name)
                if skill is None:
                    raise SkillProposalError(f"skill not found: {target_name}")
                target = skill.path
                previous = target.read_bytes() if skill.source != "bundled" else None
                if skill.source == "bundled":
                    target = _user_skill_path(skill.name)
                    target.write_text(skill.full(), encoding="utf-8")
                with target.open("a", encoding="utf-8") as fh:
                    fh.write(f"\n\n## Learned ({_today()})\n\n{addition}\n")
                _guard_agent_written(
                    target,
                    f"skill {target_name!r}",
                    previous=previous,
                )
        except store.FileLockTimeout:
            raise SkillProposalError("skill store is busy") from None
        return f"Appended learned note to {target_name!r}."
    raise SkillProposalError(f"unknown skill action: {action!r}")


def _bundled_files(directory: Path, limit: int = 40) -> list[str]:
    """Files bundled with a skill (scripts/references/templates), excluding the
    SKILL.md itself. Returned as POSIX-style paths relative to the skill dir."""
    out: list[str] = []
    try:
        for p in sorted(directory.rglob("*")):
            if p.is_file() and p.name != "SKILL.md" and "__pycache__" not in p.parts:
                out.append(p.relative_to(directory).as_posix())
                if len(out) >= limit:
                    break
    except OSError:
        pass
    return out


def _slug(name: str) -> str:
    """Canonical skill id — also the directory name and the lockfile path.

    Unicode-preserving (same semantics as ``mnemosyne.slug``): an ASCII-only
    filter collapsed every all-Hangul name to the fallback, so '번역 도우미'
    and '회의록 정리' claimed one directory and the second create failed as
    "already exists". The deterministic hash covers names that are pure
    punctuation — distinct inputs stay distinct, the same input stays stable.
    """
    s = re.sub(r"[^\w\s-]", "", name.strip().lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    if s:
        return s
    raw = name.strip()
    if not raw:
        return "skill"
    return "skill-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


def _skill_exists(canonical: str) -> bool:
    direct = config.user_skills_dir() / canonical / "SKILL.md"
    if direct.is_file():
        return True
    skills = discover(config.skill_dirs(config.load_config())).values()
    return any(
        _slug(skill.name) == canonical
        or _slug(skill.directory.name) == canonical
        for skill in skills)


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def _user_skill_path(name: str) -> Path:
    root = config.user_skills_dir().resolve()
    d = root / _slug(name)
    d.mkdir(parents=True, exist_ok=True)
    resolved = d.resolve()
    if root != resolved and root not in resolved.parents:
        raise SkillProposalError("skill path escapes the user skills directory")
    return resolved / "SKILL.md"


def _write_skill(name: str, description: str, body: str, tags: list[str]) -> Path:
    path = _user_skill_path(name)
    tag_block = "    tags: []\n" if not tags else (
        "    tags:\n" + "".join(
            f"      - {json.dumps(str(tag), ensure_ascii=False)}\n"
            for tag in tags))
    fm = (
        "---\n"
        f"name: {_slug(name)}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n"
        "version: 1.0.0\n"
        "author: birkin (self-authored)\n"
        "metadata:\n"
        "  birkin:\n"
        f"{tag_block}"
        "---\n\n"
    )
    path.write_text(fm + body.strip() + "\n", encoding="utf-8")
    return path


def build_manager(cfg: dict[str, Any]) -> SkillManager:
    return SkillManager(config.skill_dirs(cfg))
