"""The wake pipeline: local gating before any transcription, and a cooldown
that survives across daemon turns."""

from __future__ import annotations

import argparse
import importlib
from types import ModuleType

import pytest

from birkin.voice import wake as wake_mod
from birkin.voice.audio import AudioData


def _controller() -> ModuleType:
    return importlib.import_module("birkin.voice.controller")


@pytest.fixture(autouse=True)
def _fresh_wake_gates():
    # The gate cache is process-wide on purpose; tests must not inherit one.
    _controller()._WAKE_GATES.clear()
    yield
    _controller()._WAKE_GATES.clear()


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "once": True,
        "audio": None,
        "transcript": None,
        "voice_command": None,
        "command_audio": None,
        "wake_seconds": 1.0,
        "command_seconds": 1.0,
        "sample_rate": 1_000,
        "stt_model": None,
        "wake_phrase": None,
        "gateway_url": "",
        "session_id": None,
        "tts_output": None,
        "tts_model": None,
        "tts_voice": None,
        "tts_instructions": None,
        "filler_text": None,
        "no_playback": True,
        "background": False,
        "receipt_dir": None,
        "background_workers": None,
        "background_timeout": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _clap_audio() -> AudioData:
    samples = [0.0] * 1_000
    samples[400] = 1.0
    return AudioData(tuple(samples), 1_000)


def _speech_only_audio() -> AudioData:
    return AudioData(
        tuple(0.1 if index % 2 == 0 else -0.1 for index in range(1_000)),
        1_000,
    )


class _RecordingSTT:
    """Stand-in transcriber that records every call it is asked to make."""

    calls: list[str] = []

    def __init__(self, **_kwargs: object) -> None:
        pass

    def transcribe_audio(self, _audio: AudioData) -> str:
        type(self).calls.append("audio")
        return "Daddy is home"

    def transcribe_path(self, _path: str) -> str:
        type(self).calls.append("path")
        return "Daddy is home"


def _install_stt(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingSTT]:
    _RecordingSTT.calls = []
    monkeypatch.setattr(_controller(), "OpenAISTT", _RecordingSTT)
    return _RecordingSTT


def test_audio_without_a_clap_is_never_transcribed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    controller = _controller()
    stt = _install_stt(monkeypatch)
    monkeypatch.setattr(controller, "capture_microphone",
                        lambda **_kwargs: _speech_only_audio())

    assert controller.run_once(_args()) == 2

    assert stt.calls == []          # nothing left the machine
    assert "WAKE_REJECTED reason=clap_missing" in capsys.readouterr().out


def test_a_clap_earns_one_transcription(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    controller = _controller()
    stt = _install_stt(monkeypatch)
    monkeypatch.setattr(controller, "capture_microphone",
                        lambda **_kwargs: _clap_audio())

    assert controller.run_once(_args(voice_command="status")) == 0

    assert stt.calls == ["audio"]
    assert "WAKE_ACCEPTED" in capsys.readouterr().out


def test_cooldown_survives_across_turns(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    controller = _controller()
    _install_stt(monkeypatch)
    monkeypatch.setattr(controller, "capture_microphone",
                        lambda **_kwargs: _clap_audio())
    ticks = iter([100.0, 100.5])
    monkeypatch.setattr(
        controller, "WakeGate",
        lambda config: wake_mod.WakeGate(config, clock=lambda: next(ticks)))

    assert controller.run_once(_args(voice_command="status")) == 0
    assert "WAKE_ACCEPTED" in capsys.readouterr().out

    assert controller.run_once(_args(voice_command="status")) == 2

    assert "WAKE_REJECTED reason=cooldown" in capsys.readouterr().out
