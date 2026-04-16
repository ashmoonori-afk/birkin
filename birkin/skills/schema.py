"""Skill schema — definition model parsed from SKILL.md frontmatter.

A skill is a self-contained capability packaged as a directory::

    skills/
      code-review/
        SKILL.md          # Frontmatter with metadata + body with instructions
        tool.py           # Tool implementations (Tool subclasses)
        resources/        # Optional static resources

The SKILL.md frontmatter is YAML between ``---`` fences::

    ---
    name: code-review
    description: Review code for quality and security issues
    version: "0.1.0"
    triggers:
      - review
      - code review
    tools:
      - review_code
      - suggest_fix
    ---

    ## Instructions
    ...
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)


class SkillSpec(BaseModel, frozen=True):
    """Parsed SKILL.md metadata."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    version: str = "0.1.0"
    triggers: list[str] = []
    tools: list[str] = []
    enabled: bool = True


class Skill(BaseModel):
    """A loaded skill with its spec, instructions, and directory path."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    spec: SkillSpec
    instructions: str  # body of SKILL.md after frontmatter
    path: Path  # directory containing SKILL.md
    enabled: bool = True

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def tool_module_path(self) -> Optional[Path]:
        """Path to tool.py if it exists."""
        p = self.path / "tool.py"
        return p if p.is_file() else None

    @property
    def resources_dir(self) -> Optional[Path]:
        """Path to resources/ directory if it exists."""
        p = self.path / "resources"
        return p if p.is_dir() else None


def parse_skill_md(skill_path: Path) -> Optional[Skill]:
    """Parse a SKILL.md file into a Skill model.

    Args:
        skill_path: Path to a skill directory containing SKILL.md.

    Returns:
        Skill if parsing succeeds, None on error.
    """
    skill_md = skill_path / "SKILL.md"
    if not skill_md.is_file():
        logger.warning("No SKILL.md found in %s", skill_path)
        return None

    text = skill_md.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        logger.warning("Invalid SKILL.md format in %s (no frontmatter)", skill_path)
        return None

    yaml_str, body = match.group(1), match.group(2)

    try:
        frontmatter = yaml.safe_load(yaml_str)
    except yaml.YAMLError as exc:
        logger.error("Failed to parse SKILL.md YAML in %s: %s", skill_path, exc)
        return None

    if not isinstance(frontmatter, dict):
        logger.warning("SKILL.md frontmatter is not a dict in %s", skill_path)
        return None

    try:
        spec = SkillSpec(**frontmatter)
    except ValidationError as exc:
        logger.error("Invalid SKILL.md schema in %s: %s", skill_path, exc)
        return None

    return Skill(
        spec=spec,
        instructions=body.strip(),
        path=skill_path,
        enabled=spec.enabled,
    )
