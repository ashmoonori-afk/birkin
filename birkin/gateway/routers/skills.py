"""Skills router — list and toggle installed skills."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from birkin.skills.registry import SkillRegistry

router = APIRouter(prefix="/api/skills", tags=["skills"])

# Module-level singleton — initialized once, reused across requests
_registry: SkillRegistry | None = None


def _get_registry() -> SkillRegistry:
    global _registry  # noqa: PLW0603
    if _registry is None:
        _registry = SkillRegistry(skills_dir=Path("skills"))
        _registry.load_all()
    return _registry


class SkillToggleRequest(BaseModel):
    """Request body for enabling/disabling a skill."""

    enabled: bool


@router.get("")
async def list_skills() -> list[dict[str, Any]]:
    """List all installed skills with status."""
    return _get_registry().to_summary()


@router.get("/{skill_name}")
async def get_skill(skill_name: str) -> dict[str, Any]:
    """Get details for a specific skill."""
    registry = _get_registry()
    skill = registry.get_skill(skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

    tools = registry.get_skill_tools(skill_name)
    return {
        "name": skill.name,
        "description": skill.spec.description,
        "version": skill.spec.version,
        "enabled": skill.enabled,
        "triggers": skill.spec.triggers,
        "instructions": skill.instructions,
        "tools": [{"name": t.spec.name, "description": t.spec.description} for t in tools],
    }


@router.post("/{skill_name}/toggle")
async def toggle_skill(skill_name: str, body: SkillToggleRequest) -> dict[str, Any]:
    """Enable or disable a skill."""
    registry = _get_registry()
    if body.enabled:
        ok = registry.enable(skill_name)
    else:
        ok = registry.disable(skill_name)

    if not ok:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

    skill = registry.get_skill(skill_name)
    return {"name": skill_name, "enabled": skill.enabled if skill else body.enabled}
