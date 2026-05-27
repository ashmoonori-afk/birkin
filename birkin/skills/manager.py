"""SkillManager: index skills for the prompt, load them on demand, and let the
agent author/refine its own skills (the self-improvement substrate).

The model sees only a compact *index* (name + one-line description) in its
system prompt. When a skill is relevant it calls ``load_skill`` to pull the
full instructions into context — the same progressive-disclosure pattern used
by hermes and the agentskills standard.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .. import config
from .loader import Skill, discover


class SkillManager:
    def __init__(self, dirs: list[tuple[Path, str]]):
        self._dirs = dirs
        self.skills: dict[str, Skill] = discover(dirs)

    def reload(self) -> None:
        self.skills = discover(self._dirs)

    def get(self, name: str) -> Skill | None:
        if name in self.skills:
            return self.skills[name]
        low = name.lower()
        for n, s in self.skills.items():
            if n.lower() == low:
                return s
        return None

    def index(self) -> str:
        """Compact catalog for the system prompt."""
        if not self.skills:
            return "(no skills installed yet)"
        lines = []
        for s in sorted(self.skills.values(), key=lambda x: x.name):
            desc = s.description or "(no description)"
            lines.append(f"- {s.name}: {desc}")
        return "\n".join(lines)

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
            return ToolResult(f"# Skill: {skill.name}\n\n{skill.body()}")

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
            tags = inp.get("tags") or []
            path = _write_skill(name, desc, body, tags)
            self.reload()
            return ToolResult(f"Created skill {name!r} at {path}")

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
            # Only user-writable skills can be edited in place; bundled skills
            # are copied into the user dir first.
            target = skill.path
            if skill.source == "bundled":
                target = _user_skill_path(skill.name)
                target.write_text(skill.full(), encoding="utf-8")
            with target.open("a", encoding="utf-8") as fh:
                fh.write(f"\n\n## Learned ({_today()})\n\n{addition}\n")
            self.reload()
            return ToolResult(f"Appended a learned note to {name!r}.")

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
