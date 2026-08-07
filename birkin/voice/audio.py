"""Deterministic PCM/WAV helpers for voice control."""

from __future__ import annotations

import sys
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioData:
    """Normalized mono samples and their sample rate."""

    samples: tuple[float, ...]
    sample_rate: int


@dataclass(frozen=True)
class PcmFileSink:
    """Write raw PCM16/24 kHz response bytes to a configured path."""

    path: Path

    def write(self, data: bytes) -> None:
        if not data:
            raise ValueError("PCM output must not be empty")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(data)


class PcmSpeaker:
    """Play raw mono PCM16 at 24 kHz through sounddevice."""

    def write(self, data: bytes) -> None:
        if not data:
            raise ValueError("PCM output must not be empty")
        import numpy as np
        import sounddevice as sd

        samples = np.frombuffer(data, dtype="<i2")
        sd.play(samples, samplerate=24_000, blocking=True)


def read_wav_mono(path: str | Path) -> AudioData:
    """Read uncompressed 16-bit PCM WAV and average its channels."""
    source = Path(path)
    with wave.open(str(source), "rb") as stream:
        channels = stream.getnchannels()
        sample_width = stream.getsampwidth()
        sample_rate = stream.getframerate()
        compression = stream.getcomptype()
        frames = stream.readframes(stream.getnframes())

    if channels <= 0:
        raise ValueError("WAV must contain at least one channel")
    if sample_width != 2:
        raise ValueError("WAV must use 16-bit PCM samples")
    if sample_rate <= 0:
        raise ValueError("WAV sample rate must be positive")
    if compression != "NONE":
        raise ValueError("WAV must be uncompressed PCM")

    values = array("h")
    values.frombytes(frames)
    if sys.byteorder != "little":
        values.byteswap()

    normalized = tuple(value / 32_768.0 for value in values)
    if channels == 1:
        return AudioData(normalized, sample_rate)

    mono = tuple(
        sum(normalized[index:index + channels]) / channels
        for index in range(0, len(normalized), channels)
    )
    return AudioData(mono, sample_rate)
