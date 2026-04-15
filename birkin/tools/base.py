"""Tool interface definitions and base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolResult:
    """Result of executing a tool."""

    success: bool
    output: str
    error: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class ToolParameter(BaseModel, frozen=True):
    """Schema for a single tool parameter."""

    name: str
    type: str
    description: str
    required: bool = True
    default: Optional[Any] = None
    enum: Optional[list[str]] = None


class ToolSpec(BaseModel, frozen=True):
    """Metadata describing a tool for provider tool_use."""

    name: str
    description: str
    parameters: list[ToolParameter] = []
    toolset: str = "general"
    requires_env_vars: list[str] = []


@dataclass(frozen=True)
class ToolContext:
    """Context provided to a tool during execution."""

    task_id: Optional[str] = None
    session_id: Optional[str] = None
    platform: Optional[str] = None
    working_dir: Optional[str] = None
    user_id: Optional[str] = None


class Tool(ABC):
    """Abstract base class for tools.

    Every tool exposes a spec (name, description, parameters) and an
    execute method. Concrete tools are discovered by the loader and
    registered in the registry.
    """

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        """Return the tool's specification."""
        ...

    @abstractmethod
    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        """Run the tool and return a ToolResult.

        Args:
            args: Arguments passed to the tool (validated against spec.parameters).
            context: Execution context (task_id, session_id, platform, etc).

        Returns:
            ToolResult indicating success/failure and output.
        """
        ...

    def check_available(self) -> bool:
        """Check if tool is available (e.g., required env vars are set).

        Override if the tool has availability requirements.
        """
        for env_var in self.spec.requires_env_vars:
            import os

            if not os.getenv(env_var):
                return False
        return True

    def to_provider_schema(self) -> dict[str, Any]:
        """Export as a provider-agnostic JSON-schema dict."""
        params = {
            "type": "object",
            "properties": {
                p.name: {
                    "type": p.type,
                    "description": p.description,
                    **({"enum": p.enum} if p.enum else {}),
                    **({"default": p.default} if p.default is not None else {}),
                }
                for p in self.spec.parameters
            },
            "required": [p.name for p in self.spec.parameters if p.required],
        }
        return {
            "name": self.spec.name,
            "description": self.spec.description,
            "parameters": params,
        }
