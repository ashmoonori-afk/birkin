"""Type definitions for the tool system (isolated to break import cycles)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Callable,
    Literal,
    Optional,
    Protocol,
    TypeAlias,
    TypedDict,
)


class TextContentBlock(TypedDict):
    type: Literal["text"]
    text: str


class ImageSource(TypedDict):
    type: Literal["base64"]
    media_type: str
    data: str


class ImageContentBlock(TypedDict):
    type: Literal["image"]
    source: ImageSource


ToolContent: TypeAlias = str | list[TextContentBlock | ImageContentBlock]


def content_text(content: ToolContent) -> str:
    """Return visible text from a tool result without copying image data."""
    if isinstance(content, str):
        return content
    text = "\n".join(
        block["text"] for block in content if block["type"] == "text"
    )
    return text or "[image attached]"


@dataclass
class ToolResult:
    content: ToolContent
    is_error: bool = False


class LLMClientLike(Protocol):
    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        model: Optional[str] = None,
        on_text: Optional[Callable[[str], None]] = None,
        abort: Any = None,
    ) -> dict[str, Any]: ...


@dataclass
class ToolContext:
    """Everything a tool might need, passed explicitly (no globals)."""
    cfg: dict[str, Any]
    client: LLMClientLike | None
    cwd: Path
    skills: Any = None          # skills.manager.SkillManager
    memory: Any = None          # memory.Memory
    depth: int = 0              # subagent recursion depth
    max_depth: int = 2
    emit: Optional[Callable[[str, dict[str, Any]], None]] = None
    subagent_approval_required: bool = False
    approved_work: bool = False
    # Dangerous-command gate (see shellguard.py). ``shell_prompt_cb`` is
    # set only by interactive surfaces:
    #     (command, why) -> once|session|always|deny
    # Without it a flagged command is queued for approval instead.
    shell_prompt_cb: Optional[Callable[[str, str], str]] = None
    shellguard_approved: set[str] = field(default_factory=set)
    # checkpoints.CheckpointManager — snapshots the workspace before a
    # mutating tool runs, so /rollback can undo it.
    checkpoints: Any = None
    # hooks.HookBus — user shell scripts on tool lifecycle events.
    hooks: Any = None


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[[dict[str, Any], ToolContext], ToolResult]
