"""Discover ``SKILL.md`` skills across bundled, user, and extra directories.

A *skill* is any directory containing a ``SKILL.md`` file (searched
recursively, so category folders like ``research/arxiv/SKILL.md`` work). The
frontmatter's ``name`` and ``description`` are read eagerly; the markdown body
is loaded lazily when the agent actually needs it.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..executable_resolution import CommandResolution, ExecutableResolver
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
    _resolver: ExecutableResolver = field(
        default_factory=ExecutableResolver,
        repr=False,
        compare=False,
    )

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

    def body(self) -> str:
        if self._body is None:
            text = self.path.read_text(encoding="utf-8", errors="replace")
            _, body = frontmatter.split_frontmatter(text)
            self._body = body.strip()
        return self._body

    def full(self) -> str:
        return self.path.read_text(encoding="utf-8", errors="replace")

    def _platform_matches(self) -> bool:
        pre = self.meta.get("prerequisites")
        if not isinstance(pre, dict):
            pre = {}
        declared = self.meta.get("platforms")
        if not isinstance(declared, list):
            declared = pre.get("platforms") or []
        platforms = [str(p).lower() for p in declared]
        return not platforms or _current_platform() in platforms

    def _command_resolutions(self) -> tuple[CommandResolution, ...]:
        pre = self.meta.get("prerequisites")
        if not isinstance(pre, dict):
            return ()
        return tuple(
            self._resolver.resolve(str(command))
            for command in pre.get("commands") or []
        )

    @property
    def prerequisite_diagnostics(self) -> tuple[CommandResolution, ...]:
        """Return typed failures for required command execution probes."""
        if not self._platform_matches():
            return ()
        return tuple(
            result for result in self._command_resolutions()
            if not result.usable
        )

    @property
    def eligible(self) -> bool:
        """Whether platform and execution-probed prerequisites are satisfied."""
        if not self._platform_matches():
            return False
        return all(result.usable for result in self._command_resolutions())


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
            rel = skill_md.relative_to(base)
            # Hidden trees are not catalog: .archive (curator), .git, …
            if any(part.startswith(".") for part in rel.parts):
                continue
            skill = _load_skill(skill_md, source)
            if skill:
                skills[skill.name] = skill
    return skills
