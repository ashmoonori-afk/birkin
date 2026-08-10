"""Active voice-control primitives."""

from .audio import (
    AudioData,
    PcmFileSink,
    PcmSpeaker,
    capture_microphone,
    encode_wav,
    read_wav_mono,
)
from .config import VoiceConfig
from .gateway import GatewayClient, GatewayVoiceError
from .mission import VoiceMissionService
from .openai_voice import OpenAISTT, OpenAITTS
from .wake import WakeConfig, WakeDecision, WakeGate

__all__ = [
    "AudioData",
    "GatewayClient",
    "GatewayVoiceError",
    "OpenAISTT",
    "OpenAITTS",
    "PcmFileSink",
    "PcmSpeaker",
    "VoiceConfig",
    "VoiceMissionService",
    "WakeConfig",
    "WakeDecision",
    "WakeGate",
    "capture_microphone",
    "encode_wav",
    "read_wav_mono",
]
