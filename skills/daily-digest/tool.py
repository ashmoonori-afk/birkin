"""Daily digest skill — tool implementations."""

from __future__ import annotations

from typing import Any

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec


class DailyDigestTool(Tool):
    """Generate a daily digest placeholder."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="daily_digest",
            description=(
                "Return a daily digest summary. Currently a placeholder — "
                "actual news fetching requires network access."
            ),
            parameters=[
                ToolParameter(
                    name="count",
                    type="string",
                    description="Number of items to include in the digest",
                    required=False,
                    default="5",
                ),
            ],
            toolset="skills",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        count = args.get("count", "5")

        if not count.strip():
            return ToolOutput(
                success=False,
                output="",
                error="Invalid count value — must be a non-empty string",
            )

        try:
            num = int(count)
        except ValueError:
            return ToolOutput(
                success=False,
                output="",
                error=f"Count must be a numeric string, got: '{count}'",
            )

        if num < 1:
            return ToolOutput(
                success=False,
                output="",
                error="Count must be at least 1",
            )

        return ToolOutput(
            success=True,
            output=(
                f"Daily digest (top {num} items) requires LLM context. "
                "Use in chat: 'Give me today's digest'"
            ),
        )
