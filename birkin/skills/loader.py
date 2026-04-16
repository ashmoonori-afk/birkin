"""Skill loader — scan directories for skills and load their tool implementations."""

from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path
from typing import Optional

from birkin.skills.schema import Skill, parse_skill_md
from birkin.tools.base import Tool

logger = logging.getLogger(__name__)

_DEFAULT_SKILLS_DIR = Path("skills")


class SkillLoader:
    """Scans a skills directory and loads Skill definitions with their tools."""

    def __init__(self, skills_dir: Optional[Path] = None) -> None:
        self._skills_dir = skills_dir or _DEFAULT_SKILLS_DIR

    @property
    def skills_dir(self) -> Path:
        return self._skills_dir

    def discover(self) -> list[Skill]:
        """Scan the skills directory and return all valid skills.

        Each subdirectory containing a SKILL.md is treated as a skill.
        """
        if not self._skills_dir.is_dir():
            logger.info("Skills directory not found: %s", self._skills_dir)
            return []

        skills: list[Skill] = []
        for entry in sorted(self._skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith((".", "_")):
                continue

            skill = parse_skill_md(entry)
            if skill is not None:
                skills.append(skill)
                logger.info("Discovered skill: %s (%s)", skill.name, entry)

        return skills

    @staticmethod
    def load_tools(skill: Skill) -> list[Tool]:
        """Load Tool subclasses from a skill's tool.py module.

        Args:
            skill: A loaded Skill with a path to its directory.

        Returns:
            List of instantiated Tool objects from the skill.
        """
        tool_path = skill.tool_module_path
        if tool_path is None:
            return []

        try:
            spec = importlib.util.spec_from_file_location(
                f"birkin.skills.{skill.name}.tool",
                tool_path,
            )
            if not spec or not spec.loader:
                logger.warning("Could not create module spec for %s", tool_path)
                return []

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            tools: list[Tool] = []
            for name, obj in inspect.getmembers(module):
                if inspect.isclass(obj) and issubclass(obj, Tool) and obj is not Tool:
                    try:
                        instance = obj()
                        tools.append(instance)
                        logger.info("Loaded skill tool: %s/%s", skill.name, instance.spec.name)
                    except (TypeError, ValueError, RuntimeError) as exc:
                        logger.error("Failed to instantiate tool %s from %s: %s", name, tool_path, exc)

            return tools
        except (ImportError, OSError, RuntimeError) as exc:
            logger.error("Failed to load tool module from %s: %s", tool_path, exc)
            return []
