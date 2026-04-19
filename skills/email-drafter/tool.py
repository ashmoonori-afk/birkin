"""Email drafter skill — tool implementations."""

from __future__ import annotations

from typing import Any

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec

_TONE_TEMPLATES: dict[str, dict[str, str]] = {
    "professional": {
        "greeting": "Dear",
        "signoff": "Best regards",
    },
    "friendly": {
        "greeting": "Hi",
        "signoff": "Cheers",
    },
    "formal": {
        "greeting": "Dear Sir/Madam",
        "signoff": "Yours sincerely",
    },
    "casual": {
        "greeting": "Hey",
        "signoff": "Thanks",
    },
}


class DraftEmailTool(Tool):
    """Draft an email from structured inputs and a tone preset."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="draft_email",
            description=(
                "Draft an email with the given recipient, subject, context, and tone. Returns formatted email text."
            ),
            parameters=[
                ToolParameter(
                    name="to",
                    type="string",
                    description="Recipient email address or name",
                ),
                ToolParameter(
                    name="subject",
                    type="string",
                    description="Email subject line",
                ),
                ToolParameter(
                    name="context",
                    type="string",
                    description="Key points or context to include in the body",
                ),
                ToolParameter(
                    name="tone",
                    type="string",
                    description="Tone of the email (professional, friendly, formal, casual)",
                    required=False,
                    default="professional",
                ),
            ],
            toolset="skills",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        to = args.get("to", "")
        subject = args.get("subject", "")
        body_context = args.get("context", "")
        tone = args.get("tone", "professional")

        if not to.strip():
            return ToolOutput(success=False, output="", error="Recipient (to) is required")

        if not subject.strip():
            return ToolOutput(success=False, output="", error="Subject is required")

        if not body_context.strip():
            return ToolOutput(success=False, output="", error="Context is required")

        template = _TONE_TEMPLATES.get(tone.lower(), _TONE_TEMPLATES["professional"])
        greeting = template["greeting"]
        signoff = template["signoff"]

        recipient_name = to.split("@")[0] if "@" in to else to

        email = (
            f"To: {to}\nSubject: {subject}\n\n{greeting} {recipient_name},\n\n{body_context}\n\n{signoff},\n[Your Name]"
        )

        return ToolOutput(success=True, output=email)
