"""Validated configuration for one-shot voice control."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .styles import VoiceConversationStyle, parse_conversation_style


def _text(
    values: Mapping[str, object],
    key: str,
    default: str,
    *,
    allow_empty: bool = False,
) -> str:
    value = values.get(key, default)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"voice.{key} must be a string")
    return value


def _positive_int(
    values: Mapping[str, object],
    key: str,
    default: int,
) -> int:
    value = values.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"voice.{key} must be a positive integer")
    return value


@dataclass(frozen=True)
class VoiceConfig:
    """Merged voice defaults; explicit CLI flags override these values."""

    wake_phrase: str = "Daddy is home"
    gateway_url: str = ""
    session_id: str = "voice-local"
    sample_rate: int = 24_000
    stt_model: str = "gpt-transcribe"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "coral"
    tts_instructions: str = "Speak concisely and clearly."
    filler_text: str = "On it."
    conversation_style: VoiceConversationStyle = ""
    background_workers: int = 2

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, object],
    ) -> VoiceConfig:
        return cls(
            wake_phrase=_text(values, "wake_phrase", cls.wake_phrase),
            gateway_url=_text(
                values,
                "gateway_url",
                cls.gateway_url,
                allow_empty=True,
            ),
            session_id=_text(values, "session_id", cls.session_id),
            sample_rate=_positive_int(
                values,
                "sample_rate",
                cls.sample_rate,
            ),
            stt_model=_text(values, "stt_model", cls.stt_model),
            tts_model=_text(values, "tts_model", cls.tts_model),
            tts_voice=_text(values, "tts_voice", cls.tts_voice),
            tts_instructions=_text(
                values,
                "tts_instructions",
                cls.tts_instructions,
                allow_empty=True,
            ),
            filler_text=_text(
                values,
                "filler_text",
                cls.filler_text,
                allow_empty=True,
            ),
            conversation_style=parse_conversation_style(
                values.get("conversation_style", cls.conversation_style)
            ),
            background_workers=_positive_int(
                values,
                "background_workers",
                cls.background_workers,
            ),
        )

    def with_overrides(
        self,
        *,
        wake_phrase: str | None,
        gateway_url: str | None,
        session_id: str | None,
        sample_rate: int | None,
        stt_model: str | None,
        tts_model: str | None,
        tts_voice: str | None,
        tts_instructions: str | None,
        filler_text: str | None,
        background_workers: int | None,
    ) -> VoiceConfig:
        return VoiceConfig(
            wake_phrase=self.wake_phrase if wake_phrase is None else wake_phrase,
            gateway_url=self.gateway_url if gateway_url is None else gateway_url,
            session_id=self.session_id if session_id is None else session_id,
            sample_rate=self.sample_rate if sample_rate is None else sample_rate,
            stt_model=self.stt_model if stt_model is None else stt_model,
            tts_model=self.tts_model if tts_model is None else tts_model,
            tts_voice=self.tts_voice if tts_voice is None else tts_voice,
            tts_instructions=(
                self.tts_instructions
                if tts_instructions is None
                else tts_instructions
            ),
            filler_text=(
                self.filler_text
                if filler_text is None
                else filler_text
            ),
            conversation_style=self.conversation_style,
            background_workers=(
                self.background_workers
                if background_workers is None
                else background_workers
            ),
        )
