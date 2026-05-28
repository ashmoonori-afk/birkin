"""SkillManager: index skills for the prompt, load them on demand, and let the
agent author/refine its own skills (the self-improvement substrate).

The model sees only a compact *index* (name + one-line description) in its
system prompt. When a skill is relevant it calls ``load_skill`` to pull the
full instructions into context — the same progressive-disclosure pattern used
by hermes and the agentskills standard.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .. import config
from .loader import Skill, discover


class SkillManager:
    def __init__(self, dirs: list[tuple[Path, str]]):
        self._dirs = dirs
        self.skills: dict[str, Skill] = discover(dirs)
        self._sig = self._signature()
        self._checked_at = time.monotonic()

    def reload(self) -> None:
        self.skills = discover(self._dirs)
        self._sig = self._signature()

    def _signature(self) -> tuple:
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
        terms = [t for t in re.split(r"[^a-z0-9]+", (query or "").lower()) if len(t) > 2]
        skills = self.eligible_skills()
        if not terms or not skills:
            return []
        scored: list[tuple[int, Skill]] = []
        for s in skills:
            hay = f"{s.name} {s.description} {' '.join(s.tags)}".lower()
            score = sum(3 for t in terms if t in hay)
            if score == 0:  # fall back to a cheaper body scan
                body = s.body().lower()
                score = sum(1 for t in terms if t in body)
            if score:
                scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:limit]]

    def render_skill(self, skill: Skill) -> str:
        """Full skill text plus its bundled files + directory (for execution)."""
        out = f"# Skill: {skill.name}\n\n{skill.body()}"
        extras = _bundled_files(skill.directory)
        if extras:
            listing = "\n".join(f"- {p}" for p in extras)
            out += (f"\n\n## Bundled files (in this skill's directory)\n"
                    f"Skill directory: `{skill.directory}`\n{listing}\n\n"
                    f"To run a bundled script, run it with the skill directory "
                    f"as the working directory (e.g. `python scripts/<name>.py ...`).")
        return out

    # -- tools -------------------------------------------------------------

    def tools(self):
        from ..tools import Tool, ToolContext, ToolResult

        def load_skill(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            name = inp.get("name", "").strip()
            skill = self.get(name)
            if not skill:
                avail = ", ".join(sorted(self.skills)) or "(none)"
                return ToolResult(f"No skill named {name!r}. Available: {avail}",
                                  is_error=True)
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
                cfg=ctx.cfg, origin="agent")
            self.reload()
            if res.get("auto"):
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
                cfg=ctx.cfg, origin="agent")
            self.reload()
            if res.get("auto"):
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


def apply_skill_proposal(payload: dict[str, Any]) -> str:
    """Carry out an approved skill change (create / improve). Returns a human
    summary. Used by ``approvals.execute_action(category="skill")``."""
    action = (payload or {}).get("action")
    if action == "create":
        name = payload.get("name", "").strip()
        desc = payload.get("description", "").strip()
        body = payload.get("body", "").strip()
        if not (name and desc and body):
            return "skill create proposal missing name/description/body"
        path = _write_skill(name, desc, body, payload.get("tags") or [])
        return f"Created skill {name!r} at {path}"
    if action == "improve":
        target_name = payload.get("target", "").strip()
        addition = payload.get("addition", "").strip()
        if not (target_name and addition):
            return "skill improve proposal missing target/addition"
        # Locate the skill via a fresh discover so we don't depend on a Manager
        # instance from the calling context.
        from .. import config as _config
        dirs: list[tuple[Path, str]] = []
        for d in _config.bundled_skills_dirs():
            dirs.append((d, "bundled"))
        dirs.append((_config.user_skills_dir(), "user"))
        skills = discover(dirs)
        skill = skills.get(target_name)
        if skill is None:
            return f"skill not found: {target_name}"
        # Bundled (official) skills aren't edited in place — fork into the user
        # dir first so the bundled catalog stays immutable.
        target = skill.path
        if skill.source == "bundled":
            target = _user_skill_path(skill.name)
            target.write_text(skill.full(), encoding="utf-8")
        with target.open("a", encoding="utf-8") as fh:
            fh.write(f"\n\n## Learned ({_today()})\n\n{addition}\n")
        return f"Appended learned note to {target_name!r}."
    return f"unknown skill action: {action!r}"


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
    s = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")
    return s or "skill"


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def _user_skill_path(name: str) -> Path:
    d = config.user_skills_dir() / _slug(name)
    d.mkdir(parents=True, exist_ok=True)
    return d / "SKILL.md"


def _write_skill(name: str, description: str, body: str, tags: list[str]) -> Path:
    path = _user_skill_path(name)
    tag_list = ", ".join(str(t) for t in tags)
    fm = (
        "---\n"
        f"name: {_slug(name)}\n"
        f'description: "{description}"\n'
        "version: 1.0.0\n"
        "author: birkin (self-authored)\n"
        "metadata:\n"
        "  birkin:\n"
        f"    tags: [{tag_list}]\n"
        "---\n\n"
    )
    path.write_text(fm + body.strip() + "\n", encoding="utf-8")
    return path


def build_manager(cfg: dict[str, Any]) -> SkillManager:
    dirs: list[tuple[Path, str]] = []
    for d in config.bundled_skills_dirs():
        dirs.append((d, "bundled"))
    for extra in cfg.get("extra_skill_dirs", []) or []:
        dirs.append((Path(extra).expanduser(), "extra"))
    dirs.append((config.user_skills_dir(), "user"))  # user shadows bundled
    return SkillManager(dirs)
