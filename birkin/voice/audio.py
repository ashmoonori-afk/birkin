"""Deterministic PCM/WAV helpers for voice control."""

from __future__ import annotations

import sys
import wave
from array import array
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol


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


class _SampleVector(Protocol):
    def tolist(self) -> list[float]: ...


class _SampleMatrix(Protocol):
    def reshape(self, size: int) -> _SampleVector: ...


class Recorder(Protocol):
    def rec(
        self,
        frames: int,
        *,
        samplerate: int,
        channels: int,
        dtype: str,
    ) -> _SampleMatrix: ...

    def wait(self) -> None: ...


def capture_microphone(
    *,
    duration_seconds: float,
    sample_rate: int = 24_000,
    recorder: Recorder | None = None,
) -> AudioData:
    """Capture one bounded mono float32 window from the default microphone."""
    if duration_seconds <= 0.0:
        raise ValueError("duration_seconds must be positive")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if recorder is None:
        import sounddevice as sd

        recorder = sd
    frame_count = round(duration_seconds * sample_rate)
    captured = recorder.rec(
        frame_count,
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
    )
    recorder.wait()
    samples = tuple(float(value) for value in captured.reshape(-1).tolist())
    return AudioData(samples, sample_rate)


def encode_wav(audio: AudioData) -> bytes:
    """Encode normalized mono samples as uncompressed 16-bit PCM WAV."""
    pcm = array(
        "h",
        (
            round(max(-1.0, min(1.0, sample)) * 32_767)
            for sample in audio.samples
        ),
    )
    if sys.byteorder != "little":
        pcm.byteswap()
    output = BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(audio.sample_rate)
        stream.writeframes(pcm.tobytes())
    return output.getvalue()


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
