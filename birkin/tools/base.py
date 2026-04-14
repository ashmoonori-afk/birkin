"""Tool interface definition."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ToolParameter(BaseModel, frozen=True):
    """Schema for a single tool parameter."""

    name: str
    type: str
    description: str
    required: bool = True


class ToolSpec(BaseModel, frozen=True):
    """Metadata describing a tool for provider tool_use."""

    name: str
    description: str
    parameters: list[ToolParameter] = []


class Tool(ABC):
    """Abstract base class for tools.

    Every tool exposes a spec (name, description, parameters) and an
    execute method.  Concrete tools are discovered by the loader and
    registered in the registry.
    """

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        """Return the tool's specification."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """Run the tool and return a string result."""
        ...

    def to_provider_schema(self) -> dict[str, Any]:
        """Export as a provider-agnostic JSON-schema dict."""
        params = {
            "type": "object",
            "properties": {
                p.name: {"type": p.type, "description": p.description}
                for p in self.spec.parameters
            },
            "required": [p.name for p in self.spec.parameters if p.required],
        }
        return {
            "name": self.spec.name,
            "description": self.spec.description,
            "parameters": params,
        }
