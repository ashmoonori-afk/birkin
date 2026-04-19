"""Meeting prep skill — tool implementations."""

from __future__ import annotations

from typing import Any

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec


class MeetingPrepTool(Tool):
    """Generate a time-boxed meeting agenda with template questions."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="meeting_prep",
            description=(
                "Generate a time-boxed meeting agenda based on a topic and "
                "duration. Includes template discussion questions."
            ),
            parameters=[
                ToolParameter(
                    name="topic",
                    type="string",
                    description="The meeting topic or title",
                ),
                ToolParameter(
                    name="duration_minutes",
                    type="string",
                    description="Total meeting duration in minutes",
                    required=False,
                    default="30",
                ),
            ],
            toolset="skills",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        topic = args.get("topic", "")
        duration_str = args.get("duration_minutes", "30")

        if not topic.strip():
            return ToolOutput(success=False, output="", error="Meeting topic is required")

        try:
            duration = int(duration_str)
        except ValueError:
            return ToolOutput(
                success=False,
                output="",
                error=f"Duration must be a numeric string, got: '{duration_str}'",
            )

        if duration < 5:
            return ToolOutput(
                success=False,
                output="",
                error="Meeting duration must be at least 5 minutes",
            )

        agenda = self._build_agenda(topic, duration)
        return ToolOutput(success=True, output=agenda)

    @staticmethod
    def _build_agenda(topic: str, duration: int) -> str:
        """Build a time-boxed agenda proportional to duration."""
        # Allocate time proportionally
        intro_min = max(2, duration // 6)
        action_min = max(3, duration // 6)
        discussion_min = duration - intro_min - action_min

        sections = [
            f"Meeting: {topic}",
            f"Duration: {duration} minutes",
            "",
            "--- AGENDA ---",
            "",
            f"1. Introduction & Context ({intro_min} min)",
            "   - Welcome and attendance",
            "   - Recap of previous action items",
            "   - Set objectives for this session",
            "",
            f"2. Discussion: {topic} ({discussion_min} min)",
            "   - Current status and updates",
            "   - Key decisions needed",
            "   - Open questions and blockers",
            "",
            f"3. Action Items & Wrap-up ({action_min} min)",
            "   - Summarize decisions made",
            "   - Assign action items with owners and deadlines",
            "   - Confirm next meeting date",
            "",
            "--- TEMPLATE QUESTIONS ---",
            "",
            f"- What is the current status of {topic}?",
            "- What are the main blockers or risks?",
            "- What decisions need to be made today?",
            "- Who is responsible for each action item?",
            "- When is the next checkpoint?",
        ]

        return "\n".join(sections)
