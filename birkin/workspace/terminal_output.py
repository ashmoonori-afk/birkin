"""Sole event-blocking terminal output reader and command claim handoff."""

from __future__ import annotations

import codecs
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import final

from .contracts import ProtocolError
from .terminal_process import TerminalProcess
from .terminal_redaction import SensitiveValueRegistry, StreamingLiteralMasker

_READ_SIZE = 16_384


def bounded_output(value: str, limit: int) -> str:
    return value.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


@dataclass(frozen=True, slots=True)
class TerminalOutputBatch:
    text: str
    exited: bool


@final
class TerminalOutputPump:
    """Own one terminal process reader and publish unclaimed runtime output."""

    def __init__(
        self,
        process: TerminalProcess,
        registry: SensitiveValueRegistry,
        output: Callable[[str], None],
        exited: Callable[[], None],
    ) -> None:
        self._process = process
        self._masker = StreamingLiteralMasker(registry)
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._output = output
        self._exited = exited
        self._condition = threading.Condition()
        self._claimed = False
        self._claimed_text: list[str] = []
        self._done = False
        self._suppress = False
        self._thread = threading.Thread(
            target=self._run,
            name=f"birkin-terminal-output-{process.pid}",
        )

    def claim(self) -> None:
        with self._condition:
            if self._claimed:
                raise ProtocolError("terminal output is already claimed")
            self._claimed = True

    def start(self) -> None:
        self._thread.start()

    def drain(self, timeout: float) -> TerminalOutputBatch:
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self._done:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._condition.wait(remaining):
                    break
            text = "".join(self._claimed_text)
            self._claimed_text.clear()
            exited = self._done
            self._claimed = False
            self._condition.notify_all()
        return TerminalOutputBatch(text, exited)

    def stop(self, *, suppress_events: bool = False) -> None:
        with self._condition:
            self._suppress = suppress_events

    def join(self, timeout: float = 10.0) -> None:
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise TimeoutError("terminal output pump did not stop")

    def clear(self) -> None:
        self._masker.clear()

    def _run(self) -> None:
        while chunk := self._process.read(_READ_SIZE, None):
            masked = self._masker.feed(chunk)
            if masked:
                self._publish(self._decoder.decode(masked, final=False))
        final_bytes = self._masker.feed(b"", final=True)
        final_text = self._decoder.decode(final_bytes, final=True)
        if final_text:
            self._publish(final_text)
        with self._condition:
            self._done = True
            claimed, suppressed = self._claimed, self._suppress
            self._condition.notify_all()
        if not claimed and not suppressed:
            self._exited()

    def _publish(self, text: str) -> None:
        if not text:
            return
        with self._condition:
            claimed, suppressed = self._claimed, self._suppress
            if claimed:
                self._claimed_text.append(text)
                self._condition.notify_all()
        if not claimed and not suppressed:
            self._output(text)
