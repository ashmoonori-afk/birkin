"""Discover ``SKILL.md`` skills across bundled, user, and extra directories.

A *skill* is any directory containing a ``SKILL.md`` file (searched
recursively, so category folders like ``research/arxiv/SKILL.md`` work). The
frontmatter's ``name`` and ``description`` are read eagerly; the markdown body
is loaded lazily when the agent actually needs it.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import frontmatter


def _current_platform() -> str:
    if os.name == "nt":
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


@dataclass
class Skill:
    name: str
    description: str
    path: Path  # the SKILL.md file
    source: str  # "bundled" | "user" | "extra"
    meta: dict[str, Any] = field(default_factory=dict)
    _body: str | None = field(default=None, repr=False)

    @property
    def directory(self) -> Path:
        return self.path.parent

    @property
    def tags(self) -> list[str]:
        md = self.meta.get("metadata", {})
        if isinstance(md, dict):
            for ns in ("birkin", "hermes"):
                sub = md.get(ns)
                if isinstance(sub, dict) and isinstance(sub.get("tags"), list):
                    return [str(t) for t in sub["tags"]]
        tags = self.meta.get("tags")
        return [str(t) for t in tags] if isinstance(tags, list) else []

    def _meta_get(self, key: str) -> Any:
        """Read ``key`` from top-level frontmatter or under ``metadata.birkin``."""
        if self.meta.get(key) is not None:
            return self.meta.get(key)
        md = self.meta.get("metadata", {})
        if isinstance(md, dict) and isinstance(md.get("birkin"), dict):
            return md["birkin"].get(key)
        return None

    @property
    def permissions(self) -> dict[str, list[str]]:
        """Per-skill scoped permissions / MCP (v2 #8), from frontmatter
        ``permissions:`` (a list = allow-list, or ``{allow, deny}``) and ``mcp:``.
        Empty allow = unrestricted (minus any deny)."""
        perms = self._meta_get("permissions")
        allow: Any = None
        deny: Any = None
        if isinstance(perms, list):
            allow = perms
        elif isinstance(perms, dict):
            allow, deny = perms.get("allow"), perms.get("deny")
        return {
            "allow": [str(t) for t in (allow or [])],
            "deny": [str(t) for t in (deny or [])],
            "mcp": [str(m) for m in (self._meta_get("mcp") or [])],
        }

    def tool_allowed(self, tool_name: str) -> bool:
        """Whether ``tool_name`` is in this skill's scope. Empty allow-list =
        everything allowed (minus deny). Consult when permissions are enforced."""
        p = self.permissions
        if tool_name in p["deny"]:
            return False
        return (tool_name in p["allow"]) if p["allow"] else True

    def body(self) -> str:
        if self._body is None:
            text = self.path.read_text(encoding="utf-8", errors="replace")
            _, body = frontmatter.split_frontmatter(text)
            self._body = body.strip()
        return self._body

    def full(self) -> str:
        return self.path.read_text(encoding="utf-8", errors="replace")

    @property
    def eligible(self) -> bool:
        """False if the skill's frontmatter ``prerequisites`` aren't met on this
        machine (required commands missing, or wrong platform). Eligible skills
        are the ones shown in the index / used by the router."""
        pre = self.meta.get("prerequisites")
        if not isinstance(pre, dict):
            return True
        for cmd in pre.get("commands") or []:
            if shutil.which(str(cmd)) is None:
                return False
        platforms = [str(p).lower() for p in (pre.get("platforms") or [])]
        if platforms and _current_platform() not in platforms:
            return False
        return True


def _load_skill(skill_md: Path, source: str) -> Skill | None:
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    meta, _ = frontmatter.extract_meta(text)
    name = str(meta.get("name") or skill_md.parent.name).strip()
    desc = str(meta.get("description") or "").strip()
    if not name:
        return None
    return Skill(name=name, description=desc, path=skill_md, source=source, meta=meta)


def discover(dirs: list[tuple[Path, str]]) -> dict[str, Skill]:
    """Scan ``[(dir, source), ...]`` for SKILL.md files.

    Later directories override earlier ones on name collision, so order should
    be ``[bundled, user]`` to let user skills shadow bundled ones.
    """
    skills: dict[str, Skill] = {}
    for base, source in dirs:
        if not base or not base.is_dir():
            continue
        for skill_md in sorted(base.rglob("SKILL.md")):
            skill = _load_skill(skill_md, source)
            if skill:
                skills[skill.name] = skill
    return skills
