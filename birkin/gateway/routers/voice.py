"""Voice router — STT and TTS API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from birkin.voice.stt import OpenAIWhisperSTT
from birkin.voice.tts import CloudTTS

router = APIRouter(prefix="/api/voice", tags=["voice"])


class TTSRequest(BaseModel):
    text: str
    voice: str = "alloy"


@router.post("/stt")
async def speech_to_text(file: UploadFile, language: str = "ko") -> dict[str, Any]:
    """Transcribe uploaded audio to text."""
    try:
        stt = OpenAIWhisperSTT()
        audio = await file.read()
        text = await stt.transcribe(audio, language=language)
        return {"text": text, "language": language}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/tts")
async def text_to_speech(body: TTSRequest) -> Response:
    """Synthesize text to audio (MP3)."""
    try:
        tts = CloudTTS()
        audio = await tts.synthesize(body.text, voice=body.voice)
        return Response(content=audio, media_type="audio/mpeg")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
