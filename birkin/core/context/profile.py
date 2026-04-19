"""User profile — compiled from wiki memory, loaded at session start."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from birkin.memory.wiki import WikiMemory


class UserProfile(BaseModel):
    """User profile compiled from Wiki Memory.

    Provides structured context about the user's projects, preferences,
    and recent activity. Used by ContextInjector to personalize prompts.
    """

    current_projects: list[str] = Field(default_factory=list)
    key_entities: list[str] = Field(default_factory=list)
    communication_style: Optional[str] = None
    recent_decisions: list[str] = Field(default_factory=list)
    active_concerns: list[str] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    # Fields populated from conversation import
    job_role: Optional[str] = None
    expertise_areas: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    preferred_tools: list[str] = Field(default_factory=list)

    def to_prompt_section(self) -> str:
        """Format the profile as a text block for system prompt injection."""
        parts: list[str] = []

        if self.job_role:
            parts.append(f"**User Role:** {self.job_role}")
        if self.current_projects:
            parts.append(f"**Active Projects:** {', '.join(self.current_projects)}")
        if self.expertise_areas:
            parts.append(f"**Expertise:** {', '.join(self.expertise_areas)}")
        if self.interests:
            parts.append(f"**Interests:** {', '.join(self.interests)}")
        if self.key_entities:
            parts.append(f"**Key Entities:** {', '.join(self.key_entities)}")
        if self.preferred_tools:
            parts.append(f"**Tools:** {', '.join(self.preferred_tools)}")
        if self.communication_style:
            parts.append(f"**Communication Style:** {self.communication_style}")
        if self.recent_decisions:
            parts.append("**Recent Decisions:**")
            for d in self.recent_decisions[:5]:
                parts.append(f"  - {d}")
        if self.active_concerns:
            parts.append("**Active Concerns:**")
            for c in self.active_concerns[:5]:
                parts.append(f"  - {c}")

        return "\n".join(parts) if parts else ""

    @property
    def is_empty(self) -> bool:
        return not any(
            [
                self.current_projects,
                self.key_entities,
                self.communication_style,
                self.recent_decisions,
                self.active_concerns,
                self.job_role,
                self.expertise_areas,
                self.interests,
            ]
        )

    @classmethod
    def from_wiki(cls, memory: WikiMemory) -> UserProfile:
        """Build a UserProfile by reading profile wiki pages.

        Reads pages created by ProfileCompiler (conversation import).
        """
        profile = cls()

        user_page = memory.get_page("entities", "user-profile")
        if user_page:
            for line in user_page.split("\n"):
                if "**Role:**" in line:
                    profile.job_role = line.split("**Role:**", 1)[1].strip()

        expertise_page = memory.get_page("concepts", "user-expertise")
        if expertise_page:
            profile.expertise_areas = _extract_bullets(expertise_page)

        interests_page = memory.get_page("concepts", "user-interests")
        if interests_page:
            profile.interests = _extract_bullets(interests_page)

        projects_page = memory.get_page("concepts", "user-projects")
        if projects_page:
            profile.current_projects = _extract_bullets(projects_page)

        style_page = memory.get_page("concepts", "user-style")
        if style_page:
            body = _skip_frontmatter(style_page)
            for line in body.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith(("#", "-", "---")):
                    continue
                profile.communication_style = stripped
                break
            profile.preferred_tools = _extract_section_bullets(body, "Tools & Technologies")

        return profile


def _skip_frontmatter(content: str) -> str:
    """Strip YAML frontmatter (--- ... ---) from markdown content."""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return content


def _extract_bullets(content: str) -> list[str]:
    items = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def _extract_section_bullets(content: str, section: str) -> list[str]:
    in_section = False
    items = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## ") and section in stripped:
            in_section = True
            continue
        if stripped.startswith("## ") and in_section:
            break
        if in_section and stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items
