"""Text-to-speech — synthesize text to audio."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class TextToSpeech(ABC):
    """Abstract TTS interface."""

    @abstractmethod
    async def synthesize(self, text: str, *, voice: str = "alloy") -> bytes:
        """Synthesize text to audio bytes.

        Args:
            text: Text to speak.
            voice: Voice identifier.

        Returns:
            Audio bytes (MP3 format).
        """
        ...


class CloudTTS(TextToSpeech):
    """TTS via OpenAI TTS API.

    Requires OPENAI_API_KEY environment variable.
    """

    def __init__(self, *, api_key: Optional[str] = None, model: str = "tts-1") -> None:
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._model = model

    async def synthesize(self, text: str, *, voice: str = "alloy") -> bytes:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY not set for TTS")

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self._api_key)
            response = await client.audio.speech.create(
                model=self._model,
                voice=voice,
                input=text,
            )
            audio_bytes = response.content
            logger.info("TTS: synthesized %d chars → %d bytes", len(text), len(audio_bytes))
            return audio_bytes
        except ImportError:
            raise RuntimeError("openai package not installed")
        except (OSError, RuntimeError) as exc:
            logger.error("TTS failed: %s", exc)
            raise
