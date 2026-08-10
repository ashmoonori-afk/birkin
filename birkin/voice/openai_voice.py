"""OpenAI text-to-speech adapter for Birkin voice replies."""

from __future__ import annotations

from collections.abc import Iterable
from io import BytesIO
from pathlib import Path
from typing import Protocol, cast

from .audio import AudioData, encode_wav


class _SpeechResponse(Protocol):
    def iter_bytes(self) -> Iterable[bytes]: ...


class _SpeechContext(Protocol):
    def __enter__(self) -> _SpeechResponse: ...

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> object: ...


class _SpeechEndpoint(Protocol):
    def create(
        self,
        *,
        model: str,
        voice: str,
        input: str,
        instructions: str,
        response_format: str,
    ) -> _SpeechContext: ...


class _StreamingSpeech(Protocol):
    with_streaming_response: _SpeechEndpoint


class _Audio(Protocol):
    speech: _StreamingSpeech


class SpeechClient(Protocol):
    audio: _Audio


class _TranscriptResponse(Protocol):
    text: str


class _Transcriptions(Protocol):
    def create(
        self,
        *,
        model: str,
        file: object,
    ) -> _TranscriptResponse: ...


class _TranscriptionAudio(Protocol):
    transcriptions: _Transcriptions


class TranscriptionClient(Protocol):
    audio: _TranscriptionAudio


class _NamedBytesIO(BytesIO):
    name = "audio.wav"


class OpenAISTT:
    """Transcribe recorded or in-memory WAV through the official SDK."""

    def __init__(
        self,
        *,
        client: TranscriptionClient | None = None,
        model: str = "gpt-transcribe",
    ) -> None:
        if client is None:
            from openai import OpenAI

            client = cast(TranscriptionClient, cast(object, OpenAI()))
        self._client = client
        self._model = model

    def transcribe_path(self, path: str | Path) -> str:
        source = Path(path)
        with source.open("rb") as stream:
            response = self._client.audio.transcriptions.create(
                model=self._model,
                file=stream,
            )
        return self._text(response)

    def transcribe_audio(self, audio: AudioData) -> str:
        with _NamedBytesIO(encode_wav(audio)) as stream:
            response = self._client.audio.transcriptions.create(
                model=self._model,
                file=stream,
            )
        return self._text(response)

    @staticmethod
    def _text(response: _TranscriptResponse) -> str:
        text = response.text.strip()
        if not text:
            raise ValueError("OpenAI transcription was empty")
        return text


class OpenAITTS:
    """Stream GPT audio bytes while keeping the SDK client injectable."""

    def __init__(
        self,
        *,
        client: SpeechClient | None = None,
        model: str = "gpt-4o-mini-tts",
        voice: str = "coral",
        instructions: str = "Speak concisely and clearly.",
    ) -> None:
        if client is None:
            from openai import OpenAI

            client = cast(SpeechClient, cast(object, OpenAI()))
        self._client = client
        self._model = model
        self._voice = voice
        self._instructions = instructions

    def synthesize(self, text: str) -> bytes:
        reply = text.strip()
        if not reply:
            raise ValueError("TTS input must not be empty")

        with self._client.audio.speech.with_streaming_response.create(
            model=self._model,
            voice=self._voice,
            input=reply,
            instructions=self._instructions,
            response_format="pcm",
        ) as response:
            return b"".join(response.iter_bytes())
