"""Active voice-control primitives."""

from .audio import (
    AudioData,
    PcmFileSink,
    PcmSpeaker,
    capture_microphone,
    encode_wav,
    read_wav_mono,
)
from .gateway import GatewayClient, GatewayVoiceError
from .mission import VoiceMissionService
from .openai_voice import OpenAISTT, OpenAITTS
from .wake import WakeConfig, WakeDecision, WakeGate

__all__ = [
    "AudioData",
    "GatewayClient",
    "GatewayVoiceError",
    "OpenAITTS",
    "OpenAISTT",
    "PcmFileSink",
    "PcmSpeaker",
    "VoiceMissionService",
    "capture_microphone",
    "encode_wav",
    "WakeConfig",
    "WakeDecision",
    "WakeGate",
    "read_wav_mono",
]
