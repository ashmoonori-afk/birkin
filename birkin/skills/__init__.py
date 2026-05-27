"""Skill discovery, loading, and authoring (agentskills.io / hermes compatible)."""

from .loader import Skill, discover
from .manager import SkillManager, build_manager

__all__ = ["Skill", "discover", "SkillManager", "build_manager"]
