"""Shared deterministic skill selection and prompt rendering."""

from __future__ import annotations

from dataclasses import dataclass

from ..office.skill_router import route_office_request
from .manager import SkillManager


@dataclass(frozen=True, slots=True)
class RoutedSkills:
    """Machine identifiers and rendered prompts selected for one turn."""

    names: tuple[str, ...]
    rendered: tuple[str, ...]


def assemble_routed_skills(
    manager: SkillManager,
    text: str,
    loaded_skills: set[str] | None = None,
) -> RoutedSkills:
    """Select and render skills exactly as a production turn does."""
    office_route = route_office_request(text)
    office_skill = (
        manager.get(office_route.skill_name) if office_route is not None else None
    )
    selected = (
        [office_skill]
        if office_skill is not None and office_skill.eligible
        else manager.route(text, limit=3)
    )
    rendered = [
        manager.render_skill(skill)
        for skill in selected
        if loaded_skills is None or skill.name not in loaded_skills
    ]
    if (
        office_route is not None
        and office_route.clarification_question is not None
        and rendered
    ):
        rendered[0] = (
            "Office route clarification required. Ask the user exactly: "
            f"{office_route.clarification_question}\n"
            "Do not choose a destination format or invoke a document mutation "
            "tool until the user answers.\n\n"
            f"{rendered[0]}"
        )
    elif office_route is not None and rendered:
        source_text = ", ".join(office_route.source_formats) or "none"
        target_text = office_route.target_format or "none"
        if office_route.target_format_suggested:
            target_text += " (suggestion; the user may change it)"
        rendered[0] = (
            "Office route policy: inspect-first; write policy: "
            f"{office_route.write_policy}; source formats: {source_text}; "
            f"target format: {target_text}.\n\n{rendered[0]}"
        )
    return RoutedSkills(
        names=tuple(skill.name for skill in selected),
        rendered=tuple(rendered),
    )
