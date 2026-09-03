"""Timestamping must not hide attributes a wrapped stream resolves dynamically."""

from __future__ import annotations

from birkin.gateway.core import TimestampedStream


class _ProxyStream:
    """A stream whose .encoding only exists through __getattr__ (colorama, pytest)."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, data: str) -> int:
        self.lines.append(data)
        return len(data)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def __getattr__(self, name: str) -> object:
        if name == "encoding":
            return "utf-8"
        raise AttributeError(name)


def test_dynamically_resolved_stream_attributes_stay_reachable() -> None:
    # Given
    stream = TimestampedStream(_ProxyStream())

    # When/Then
    assert stream.encoding == "utf-8"
