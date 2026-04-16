"""User profile — compiled from wiki memory, loaded at session start."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


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

    def to_prompt_section(self) -> str:
        """Format the profile as a text block for system prompt injection."""
        parts: list[str] = []

        if self.current_projects:
            parts.append(f"**Active Projects:** {', '.join(self.current_projects)}")
        if self.key_entities:
            parts.append(f"**Key Entities:** {', '.join(self.key_entities)}")
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
            ]
        )
