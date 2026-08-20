"""Canonical data-only session launcher presets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final


@final
@dataclass(frozen=True)
class SessionPreset:
    id: str
    name: str
    prefill: str
    persistent: bool
    order: int

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "prefill": self.prefill,
            "persistent": self.persistent,
            "order": self.order,
        }


SESSION_PRESETS = (
    SessionPreset(
        id="research",
        name="Research",
        prefill="Research the following topic:\n",
        persistent=False,
        order=0,
    ),
    SessionPreset(
        id="data-analysis",
        name="Data Analysis",
        prefill="Analyze the following data:\n",
        persistent=False,
        order=1,
    ),
    SessionPreset(
        id="writing",
        name="Writing",
        prefill="Help me write:\n",
        persistent=False,
        order=2,
    ),
    SessionPreset(
        id="automation",
        name="Automation",
        prefill="Automate the following workflow:\n",
        persistent=False,
        order=3,
    ),
)
