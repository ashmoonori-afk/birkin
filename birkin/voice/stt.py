"""Speech-to-text — transcribe audio to text."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class SpeechToText(ABC):
    """Abstract STT interface."""

    @abstractmethod
    async def transcribe(self, audio: bytes, *, language: str = "ko") -> str:
        """Transcribe audio bytes to text.

        Args:
            audio: Raw audio bytes (WAV, MP3, OGG, etc.).
            language: BCP-47 language code (default: Korean).

        Returns:
            Transcribed text string.
        """
        ...


class OpenAIWhisperSTT(SpeechToText):
    """STT via OpenAI Whisper API.

    Requires OPENAI_API_KEY environment variable.
    """

    def __init__(self, *, api_key: Optional[str] = None, model: str = "whisper-1") -> None:
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._model = model

    async def transcribe(self, audio: bytes, *, language: str = "ko") -> str:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY not set for Whisper STT")

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self._api_key)
            # OpenAI expects a file-like object with a name
            import io

            audio_file = io.BytesIO(audio)
            audio_file.name = "audio.wav"

            transcript = await client.audio.transcriptions.create(
                model=self._model,
                file=audio_file,
                language=language,
            )
            result = transcript.text
            logger.info("Whisper STT: transcribed %d bytes → %d chars", len(audio), len(result))
            return result
        except ImportError as exc:
            raise RuntimeError("openai package not installed") from exc
        except (OSError, RuntimeError) as exc:
            logger.error("Whisper STT failed: %s", exc)
            raise
