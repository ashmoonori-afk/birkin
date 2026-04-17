"""Skill registry — manage installed skills and their tools."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from birkin.skills.loader import SkillLoader
from birkin.skills.schema import Skill
from birkin.tools.base import Tool

logger = logging.getLogger(__name__)

_SKILL_STATE_KEY = "disabled_skills"


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

        Restores persisted enable/disable state from config.
        """
        skills = self._loader.discover()
        for skill in skills:
            self._skills[skill.name] = skill
            self._tools[skill.name] = self._loader.load_tools(skill)

        # Restore persisted disabled state
        disabled = self._load_disabled_set()
        for name in disabled:
            if name in self._skills:
                self._skills[name].enabled = False

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
        """Enable a skill. Persists state to config."""
        skill = self._skills.get(name)
        if skill is None:
            return False
        skill.enabled = True
        self._persist_disabled_set()
        return True

    def disable(self, name: str) -> bool:
        """Disable a skill. Persists state to config."""
        skill = self._skills.get(name)
        if skill is None:
            return False
        skill.enabled = False
        self._persist_disabled_set()
        return True

    # ── Persistence helpers ──

    @staticmethod
    def _config_path() -> Path:
        import os

        return Path(os.environ.get("BIRKIN_CONFIG_PATH", "birkin_config.json"))

    def _load_disabled_set(self) -> set[str]:
        """Load the set of disabled skill names from config."""
        path = self._config_path()
        if not path.exists():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return set(data.get(_SKILL_STATE_KEY, []))
        except (json.JSONDecodeError, OSError):
            return set()

    def _persist_disabled_set(self) -> None:
        """Save the set of disabled skill names to config."""
        path = self._config_path()
        try:
            data: dict[str, Any] = {}
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            disabled = [n for n, s in self._skills.items() if not s.enabled]
            data[_SKILL_STATE_KEY] = disabled
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to persist skill state: %s", exc)

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
