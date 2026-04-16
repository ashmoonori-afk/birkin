"""Skill registry — manage installed skills and their tools."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from birkin.skills.loader import SkillLoader
from birkin.skills.schema import Skill
from birkin.tools.base import Tool

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Manages discovered skills: listing, enable/disable, and tool access.

    Usage::

        registry = SkillRegistry(skills_dir=Path("skills"))
        registry.load_all()
        tools = registry.get_enabled_tools()
    """

    def __init__(self, skills_dir: Optional[Path] = None) -> None:
        self._loader = SkillLoader(skills_dir)
        self._skills: dict[str, Skill] = {}
        self._tools: dict[str, list[Tool]] = {}  # skill_name -> tools

    @property
    def skills_dir(self) -> Path:
        return self._loader.skills_dir

    def load_all(self) -> list[Skill]:
        """Discover and load all skills from the skills directory.

        Returns:
            List of all discovered skills.
        """
        skills = self._loader.discover()
        for skill in skills:
            self._skills[skill.name] = skill
            self._tools[skill.name] = self._loader.load_tools(skill)

        logger.info(
            "Loaded %d skills with %d total tools",
            len(self._skills),
            sum(len(t) for t in self._tools.values()),
        )
        return list(self._skills.values())

    def list_skills(self) -> list[Skill]:
        """Return all registered skills."""
        return list(self._skills.values())

    def get_skill(self, name: str) -> Optional[Skill]:
        """Look up a skill by name."""
        return self._skills.get(name)

    def enable(self, name: str) -> bool:
        """Enable a skill. Returns True if found."""
        skill = self._skills.get(name)
        if skill is None:
            return False
        skill.enabled = True
        return True

    def disable(self, name: str) -> bool:
        """Disable a skill. Returns True if found."""
        skill = self._skills.get(name)
        if skill is None:
            return False
        skill.enabled = False
        return True

    def get_skill_tools(self, name: str) -> list[Tool]:
        """Get tools for a specific skill."""
        return self._tools.get(name, [])

    def get_enabled_tools(self) -> list[Tool]:
        """Return tools from all enabled skills."""
        tools: list[Tool] = []
        for skill_name, skill in self._skills.items():
            if skill.enabled:
                tools.extend(self._tools.get(skill_name, []))
        return tools

    def get_enabled_skills(self) -> list[Skill]:
        """Return only enabled skills."""
        return [s for s in self._skills.values() if s.enabled]

    def match_triggers(self, text: str) -> list[Skill]:
        """Find skills whose triggers match the given text.

        Simple case-insensitive substring match against trigger keywords.
        """
        text_lower = text.lower()
        matches: list[Skill] = []
        for skill in self._skills.values():
            if not skill.enabled:
                continue
            for trigger in skill.spec.triggers:
                if trigger.lower() in text_lower:
                    matches.append(skill)
                    break
        return matches

    def to_summary(self) -> list[dict]:
        """Export skill summaries for API responses."""
        return [
            {
                "name": skill.name,
                "description": skill.spec.description,
                "version": skill.spec.version,
                "enabled": skill.enabled,
                "triggers": skill.spec.triggers,
                "tool_count": len(self._tools.get(skill.name, [])),
            }
            for skill in self._skills.values()
        ]

    def __len__(self) -> int:
        return len(self._skills)

    def __repr__(self) -> str:
        enabled = sum(1 for s in self._skills.values() if s.enabled)
        return f"SkillRegistry({len(self._skills)} skills, {enabled} enabled)"
