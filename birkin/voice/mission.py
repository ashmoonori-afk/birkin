"""Background voice mission wiring over the existing Gateway."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from birkin.background import BackgroundBroker, JobContext, JobSnapshot

from .gateway import GatewayClient
from .openai_voice import OpenAITTS


class AudioSink(Protocol):
    def write(self, data: bytes) -> None: ...


class VoiceMissionService:
    """Submit Gateway work while persisting progress and final delivery."""

    def __init__(
        self,
        broker: BackgroundBroker,
        gateway: GatewayClient,
        *,
        tts: OpenAITTS | None = None,
        sinks: Sequence[AudioSink] = (),
    ) -> None:
        self._broker = broker
        self._gateway = gateway
        self._tts = tts
        self._sinks = tuple(sinks)

    def submit(self, command: str) -> JobSnapshot:
        text = command.strip()
        if not text:
            raise ValueError("voice mission command must not be empty")

        def run(context: JobContext) -> str:
            context.progress("gateway")
            reply = self._gateway.send(text)
            if self._tts is not None and self._sinks:
                context.progress("tts")
                pcm = self._tts.synthesize(reply)
                for sink in self._sinks:
                    sink.write(pcm)
            context.progress("delivered")
            return reply

        return self._broker.submit(text, run)
