"""Active voice-control primitives."""

from .audio import AudioData, PcmFileSink, PcmSpeaker, read_wav_mono
from .gateway import GatewayClient, GatewayVoiceError
from .openai_voice import OpenAITTS
from .wake import WakeConfig, WakeDecision, WakeGate

__all__ = [
    "AudioData",
    "GatewayClient",
    "GatewayVoiceError",
    "OpenAITTS",
    "PcmFileSink",
    "PcmSpeaker",
    "WakeConfig",
    "WakeDecision",
    "WakeGate",
    "read_wav_mono",
]
