"""Generate deterministic WAV fixtures for active-voice CLI QA."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

SAMPLE_RATE = 1_000
FRAME_COUNT = SAMPLE_RATE


def _write(path: Path, samples: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def main() -> int:
    fixtures = Path(__file__).parents[2] / "tests" / "fixtures" / "voice"

    clap = [0] * FRAME_COUNT
    clap[400] = 32_767
    _write(fixtures / "clap_then_phrase.wav", clap)

    phrase_only = [
        3_276 if index % 2 == 0 else -3_276
        for index in range(FRAME_COUNT)
    ]
    _write(fixtures / "phrase_only.wav", phrase_only)
    print(fixtures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
