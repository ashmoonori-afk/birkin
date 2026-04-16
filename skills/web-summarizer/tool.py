"""Web summarizer skill — tool implementations."""

from __future__ import annotations

import re
from typing import Any

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec


class SummarizeTextTool(Tool):
    """Extract key points from text into concise bullet points."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="summarize_text",
            description="Summarize text into concise bullet points. Extracts key sentences and topics.",
            parameters=[
                ToolParameter(
                    name="text",
                    type="string",
                    description="The text to summarize",
                ),
                ToolParameter(
                    name="max_points",
                    type="integer",
                    description="Maximum number of bullet points",
                    required=False,
                    default=7,
                ),
            ],
            toolset="skills",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        text = args.get("text", "")
        max_points = int(args.get("max_points", 7))

        if not text.strip():
            return ToolOutput(success=False, output="", error="No text provided to summarize")

        # Extractive summarization: score sentences by keyword density
        sentences = re.split(r"[.!?]\s+", text.strip())
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

        if not sentences:
            return ToolOutput(success=True, output="Text too short to summarize.")

        # Score by sentence length (proxy for information density) and position
        scored: list[tuple[float, int, str]] = []
        for i, sentence in enumerate(sentences):
            word_count = len(sentence.split())
            position_boost = 1.5 if i < 3 else (1.2 if i >= len(sentences) - 2 else 1.0)
            score = word_count * position_boost
            scored.append((score, i, sentence))

        # Take top N by score, then sort by original position
        scored.sort(key=lambda x: x[0], reverse=True)
        selected = scored[:max_points]
        selected.sort(key=lambda x: x[1])

        bullets = [f"- {s[2].rstrip('.')}" for s in selected]
        summary = f"**Summary** ({len(bullets)} key points):\n\n" + "\n".join(bullets)

        return ToolOutput(success=True, output=summary)
