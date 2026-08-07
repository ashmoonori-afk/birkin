from __future__ import annotations

import importlib
import io
import wave
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from birkin.voice.audio import AudioData
from birkin.cli import build_parser


def _openai_module() -> ModuleType:
    openai_voice = importlib.import_module("birkin.voice.openai_voice")
    if not hasattr(openai_voice, "OpenAISTT"):
        pytest.fail("OpenAI speech-to-text contract is not implemented")
    return openai_voice


def _audio_module() -> ModuleType:
    audio = importlib.import_module("birkin.voice.audio")
    if not hasattr(audio, "capture_microphone"):
        pytest.fail("microphone capture contract is not implemented")
    return audio


class _Transcriptions:
    def __init__(self) -> None:
        self.model = ""
        self.filename = ""
        self.payload = b""

    def create(self, *, model: str, file) -> SimpleNamespace:
        self.model = model
        self.filename = Path(file.name).name
        self.payload = file.read()
        return SimpleNamespace(text="  Daddy is home  ")


class _Audio:
    def __init__(self) -> None:
        self.transcriptions = _Transcriptions()


class _Client:
    def __init__(self) -> None:
        self.audio = _Audio()


def _write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24_000)
        stream.writeframes(b"\x00\x00\x01\x00")


def test_openai_stt_transcribes_recorded_wav(tmp_path: Path) -> None:
    openai_voice = _openai_module()
    path = tmp_path / "wake.wav"
    _write_wav(path)
    client = _Client()

    transcript = openai_voice.OpenAISTT(
        client=client,
        model="gpt-transcribe",
    ).transcribe_path(path)

    assert transcript == "Daddy is home"
    assert client.audio.transcriptions.model == "gpt-transcribe"
    assert client.audio.transcriptions.filename == "wake.wav"
    assert client.audio.transcriptions.payload.startswith(b"RIFF")


def test_openai_stt_encodes_in_memory_audio_as_wav() -> None:
    openai_voice = _openai_module()
    client = _Client()
    audio = AudioData(
        samples=(0.0, 0.5, -0.5),
        sample_rate=24_000,
    )

    transcript = openai_voice.OpenAISTT(
        client=client,
        model="gpt-transcribe",
    ).transcribe_audio(audio)

    assert transcript == "Daddy is home"
    assert client.audio.transcriptions.filename == "audio.wav"
    with wave.open(io.BytesIO(client.audio.transcriptions.payload)) as stream:
        assert stream.getnchannels() == 1
        assert stream.getsampwidth() == 2
        assert stream.getframerate() == 24_000
        assert stream.getnframes() == 3


class _Samples:
    def reshape(self, _size: int) -> _Samples:
        return self

    def tolist(self) -> list[float]:
        return [0.25, -0.25]


class _Recorder:
    def __init__(self) -> None:
        self.request: tuple[int, int, int, str] | None = None
        self.waited = False

    def rec(
        self,
        frames: int,
        *,
        samplerate: int,
        channels: int,
        dtype: str,
    ) -> _Samples:
        self.request = (frames, samplerate, channels, dtype)
        return _Samples()

    def wait(self) -> None:
        self.waited = True


def test_microphone_capture_uses_mono_float32_and_waits() -> None:
    audio_module = _audio_module()
    recorder = _Recorder()

    captured = audio_module.capture_microphone(
        duration_seconds=0.5,
        sample_rate=24_000,
        recorder=recorder,
    )

    assert recorder.request == (12_000, 24_000, 1, "float32")
    assert recorder.waited is True
    assert captured == AudioData((0.25, -0.25), 24_000)


def test_voice_command_flag_does_not_overwrite_subcommand() -> None:
    args = build_parser().parse_args(
        ["voice", "--once", "--audio", "wake.wav"]
    )

    assert args.command == "voice"
    assert args.voice_command is None
