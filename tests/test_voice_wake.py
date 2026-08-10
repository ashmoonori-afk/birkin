from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType
from typing import Any

import pytest


def _wake_module() -> ModuleType:
    if importlib.util.find_spec("birkin.voice") is None:
        pytest.fail("voice wake contract is not implemented")
    return importlib.import_module("birkin.voice.wake")


def _gate(**overrides: Any) -> Any:
    wake = _wake_module()
    values = {
        "wake_phrase": "Daddy is home",
        "clap_peak": 0.8,
        "clap_crest": 4.0,
        "frame_ms": 20,
        "cooldown_seconds": 2.0,
    }
    values.update(overrides)
    return wake.WakeGate(wake.WakeConfig(**values))


def _clap_pcm() -> list[float]:
    samples = [0.0] * 1_000
    samples[400] = 1.0
    return samples


def _speech_only_pcm() -> list[float]:
    return [0.1 if index % 2 == 0 else -0.1 for index in range(1_000)]


def test_clap_and_normalized_phrase_accept() -> None:
    decision = _gate().evaluate(
        _clap_pcm(),
        sample_rate=1_000,
        transcript="  ＤＡＤＤＹ,   IS HOME!!! ",
        now=10.0,
    )

    assert decision.accepted is True
    assert decision.reason == "accepted"
    assert decision.normalized_phrase == "daddy is home"


@pytest.mark.parametrize(
    ("samples", "transcript", "reason"),
    [
        (_clap_pcm(), "", "phrase_missing"),
        (_speech_only_pcm(), "Daddy is home", "clap_missing"),
        (_clap_pcm(), "Jarvis wake up", "phrase_mismatch"),
    ],
)
def test_incomplete_or_wrong_wake_is_rejected(
    samples: list[float],
    transcript: str,
    reason: str,
) -> None:
    decision = _gate().evaluate(
        samples,
        sample_rate=1_000,
        transcript=transcript,
        now=10.0,
    )

    assert decision.accepted is False
    assert decision.reason == reason


def test_cooldown_rejects_repeated_wake_until_boundary() -> None:
    gate = _gate()

    first = gate.evaluate(
        _clap_pcm(),
        sample_rate=1_000,
        transcript="Daddy is home",
        now=10.0,
    )
    repeated = gate.evaluate(
        _clap_pcm(),
        sample_rate=1_000,
        transcript="Daddy is home",
        now=11.999,
    )
    boundary = gate.evaluate(
        _clap_pcm(),
        sample_rate=1_000,
        transcript="Daddy is home",
        now=12.0,
    )

    assert first.accepted is True
    assert repeated.accepted is False
    assert repeated.reason == "cooldown"
    assert boundary.accepted is True
