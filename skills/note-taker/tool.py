"""Note taker skill — tool implementations."""

from __future__ import annotations

import re
from typing import Any

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec


class TakeNotesTool(Tool):
    """Format raw text into structured notes."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="take_notes",
            description=("Convert raw text into structured notes using the chosen style (bullet or outline)."),
            parameters=[
                ToolParameter(
                    name="content",
                    type="string",
                    description="Raw text content to convert into notes",
                ),
                ToolParameter(
                    name="style",
                    type="string",
                    description="Note style: 'bullet' or 'outline'",
                    required=False,
                    default="bullet",
                ),
            ],
            toolset="skills",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        content = args.get("content", "")
        style = args.get("style", "bullet")

        if not content.strip():
            return ToolOutput(success=False, output="", error="No content provided")

        sentences = self._split_sentences(content)

        if not sentences:
            return ToolOutput(success=False, output="", error="No sentences detected in content")

        if style == "outline":
            formatted = self._format_outline(sentences)
        else:
            formatted = self._format_bullet(sentences)

        return ToolOutput(success=True, output=formatted)

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text on sentence boundaries."""
        # Split on ". " or ".\n" or "!" or "?" while keeping non-empty results
        raw = re.split(r"(?<=[.!?])\s+", text.strip())
        return [s.strip() for s in raw if s.strip()]

    @staticmethod
    def _format_bullet(sentences: list[str]) -> str:
        """Format as a bullet list."""
        return "\n".join(f"- {sentence}" for sentence in sentences)

    @staticmethod
    def _format_outline(sentences: list[str]) -> str:
        """Format as a numbered outline with sub-detail placeholders."""
        lines: list[str] = []
        for idx, sentence in enumerate(sentences, 1):
            lines.append(f"{idx}. {sentence}")
            lines.append("   a. [detail]")
        return "\n".join(lines)
