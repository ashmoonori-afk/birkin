"""Voice-only conversation style presets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias, cast

ConversationStyle = Literal["natural", "concise", "curious", "playful"]
VoiceConversationStyle: TypeAlias = ConversationStyle | Literal[""]


@dataclass(frozen=True)
class StylePreset:
    key: ConversationStyle
    label: str
    description: str
    instruction: str


STYLE_PRESETS: tuple[StylePreset, ...] = (
    StylePreset(
        key="natural",
        label="Natural",
        description="warm, relaxed, and balanced",
        instruction=(
            "Reply like a warm, natural conversation. Be clear without "
            "sounding formal, and keep the spoken answer easy to follow."
        ),
    ),
    StylePreset(
        key="concise",
        label="Concise",
        description="short, direct, and action-first",
        instruction=(
            "Lead with the answer or next action. Use short spoken sentences "
            "and omit detail that was not requested."
        ),
    ),
    StylePreset(
        key="curious",
        label="Curious",
        description="thoughtful, reflective, and gently inquisitive",
        instruction=(
            "Respond thoughtfully and surface useful connections. Ask at most "
            "one brief follow-up question when it would improve the answer."
        ),
    ),
    StylePreset(
        key="playful",
        label="Playful",
        description="lively, expressive, and lightly humorous",
        instruction=(
            "Keep the reply lively and expressive, with light humor when it "
            "fits. Never let playfulness obscure the answer."
        ),
    ),
)

_PRESETS_BY_KEY = {preset.key: preset for preset in STYLE_PRESETS}


def parse_conversation_style(value: object) -> VoiceConversationStyle:
    if value == "":
        return ""
    if not isinstance(value, str) or value not in _PRESETS_BY_KEY:
        choices = ", ".join(_PRESETS_BY_KEY)
        raise ValueError(
            f"voice.conversation_style must be one of: {choices}"
        )
    return cast("ConversationStyle", value)


def format_voice_command(
    command: str,
    style: VoiceConversationStyle,
) -> str:
    text = command.strip()
    if not style:
        return text
    preset = _PRESETS_BY_KEY[style]
    return (
        f'{text}\n\n<voice-response-style id="{style}">\n'
        f"{preset.instruction}\n"
        "</voice-response-style>"
    )
