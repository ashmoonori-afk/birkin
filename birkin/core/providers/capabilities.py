"""Provider capability metadata for multi-LLM routing.

Each provider declares what it can do (reasoning, search, code, vision, etc.),
its cost structure, latency tier, and context window. The ProviderRouter uses
this metadata to select the best provider for a given task.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Capability(str, Enum):  # noqa: UP042
    """Capabilities a provider can declare."""

    REASONING = "reasoning"
    SEARCH = "search"
    CODE = "code"
    VISION = "vision"
    AUDIO = "audio"
    LOW_LATENCY = "low_latency"
    LONG_CONTEXT = "long_context"
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_USE = "tool_use"


class ProviderProfile(BaseModel, frozen=True):
    """Metadata about a provider's capabilities and cost.

    Attached to each Provider instance via the ``profile`` property.
    Used by ProviderRouter for automatic model selection.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    model: str
    capabilities: frozenset[Capability] = frozenset()
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    max_context: int = 4096
    latency_tier: Literal["low", "medium", "high"] = "medium"
    local: bool = False

    def supports(self, capability: Capability) -> bool:
        """Check if this provider supports a given capability."""
        return capability in self.capabilities
