"""Clap and phrase wake gate."""

from __future__ import annotations

import math
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

WakeReason = Literal[
    "accepted",
    "clap_missing",
    "phrase_missing",
    "phrase_mismatch",
    "cooldown",
]


@dataclass(frozen=True)
class WakeConfig:
    """Thresholds for one clap-plus-phrase wake decision."""

    wake_phrase: str
    clap_peak: float = 0.8
    clap_crest: float = 4.0
    frame_ms: int = 20
    cooldown_seconds: float = 2.0

    def __post_init__(self) -> None:
        if not normalize_phrase(self.wake_phrase):
            raise ValueError("wake_phrase must contain letters or digits")
        if not 0.0 < self.clap_peak <= 1.0:
            raise ValueError("clap_peak must be in (0, 1]")
        if self.clap_crest <= 1.0:
            raise ValueError("clap_crest must be greater than 1")
        if self.frame_ms <= 0:
            raise ValueError("frame_ms must be positive")
        if self.cooldown_seconds < 0.0:
            raise ValueError("cooldown_seconds must be non-negative")


@dataclass(frozen=True)
class WakeDecision:
    """Observable result of evaluating one wake window."""

    accepted: bool
    reason: WakeReason
    normalized_phrase: str


def normalize_phrase(value: str) -> str:
    """Normalize case, width, punctuation, and whitespace."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    words = "".join(
        char if char.isalnum() else " "
        for char in normalized
    )
    return " ".join(words.split())


class WakeGate:
    """Require an impulse-like clap and an exact normalized phrase."""

    def __init__(
        self,
        config: WakeConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._clock = clock
        self._last_accepted_at: float | None = None

    def evaluate(
        self,
        samples: Sequence[float],
        *,
        sample_rate: int,
        transcript: str,
        now: float | None = None,
    ) -> WakeDecision:
        """Evaluate one audio window without retaining its samples."""
        normalized = normalize_phrase(transcript)
        expected = normalize_phrase(self._config.wake_phrase)
        # The clap is judged first and locally: callers gate on has_clap() so a
        # room with no clap never has its audio sent anywhere for transcription.
        if not self.has_clap(samples, sample_rate):
            return WakeDecision(False, "clap_missing", normalized)
        if not normalized:
            return WakeDecision(False, "phrase_missing", normalized)
        if normalized != expected:
            return WakeDecision(False, "phrase_mismatch", normalized)

        accepted_at = self._clock() if now is None else now
        if (
            self._last_accepted_at is not None
            and accepted_at - self._last_accepted_at
            < self._config.cooldown_seconds
        ):
            return WakeDecision(False, "cooldown", normalized)

        self._last_accepted_at = accepted_at
        return WakeDecision(True, "accepted", normalized)

    def has_clap(
        self,
        samples: Sequence[float],
        sample_rate: int,
    ) -> bool:
        """Whether one window holds an impulse-like clap. Local, no network."""
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")

        frame_size = max(
            1,
            round(sample_rate * self._config.frame_ms / 1_000),
        )
        for offset in range(0, len(samples), frame_size):
            frame = samples[offset:offset + frame_size]
            if not frame:
                continue
            peak = max(abs(sample) for sample in frame)
            if peak < self._config.clap_peak:
                continue
            rms = math.sqrt(
                sum(sample * sample for sample in frame) / len(frame)
            )
            crest = peak / max(rms, 1e-12)
            if crest >= self._config.clap_crest:
                return True
        return False
