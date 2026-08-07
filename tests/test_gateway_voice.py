from __future__ import annotations

import importlib
import importlib.util
import json
import threading
from pathlib import Path
from types import ModuleType
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from birkin.gateway.channels.local_http import LocalHTTPChannel


class _Gateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.pending_hard_restart = False

    def handle(self, channel: str, session_id: str, text: str) -> str:
        self.calls.append((channel, session_id, text))
        return f"reply:{text}"


def _post(port: int, body: dict[str, str]) -> tuple[int, dict[str, str]]:
    request = Request(
        f"http://127.0.0.1:{port}/message",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Connection": "close",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=2.0) as response:
        payload = json.loads(response.read1(65_536).decode("utf-8"))
        return response.status, payload


def _bound_port(channel: LocalHTTPChannel) -> int:
    return channel.port


def _start_channel(
    gateway: _Gateway,
) -> tuple[LocalHTTPChannel, threading.Thread]:
    channel = LocalHTTPChannel(0)
    thread = threading.Thread(
        target=channel.start,
        args=(gateway,),
        daemon=True,
    )
    thread.start()
    assert channel.wait_until_ready(1.0)
    return channel, thread


def _stop_channel(
    channel: LocalHTTPChannel,
    thread: threading.Thread,
) -> None:
    channel.stop()
    thread.join(timeout=2.0)
    assert not thread.is_alive()


def _voice_module(name: str) -> ModuleType:
    try:
        spec = importlib.util.find_spec("birkin.voice.gateway")
    except ModuleNotFoundError:
        spec = None
    if spec is None:
        pytest.fail("voice gateway and TTS contract is not implemented")
    return importlib.import_module(name)


def test_local_http_preserves_explicit_voice_channel() -> None:
    gateway = _Gateway()
    channel, thread = _start_channel(gateway)
    try:
        status, payload = _post(
            _bound_port(channel),
            {
                "channel": "voice",
                "session": "voice-fixed",
                "text": "status",
            },
        )
    finally:
        _stop_channel(channel, thread)

    assert status == 200
    assert payload == {"reply": "reply:status"}
    assert gateway.calls == [("voice", "voice-fixed", "status")]


def test_local_http_rejects_trusted_channel_spoof() -> None:
    gateway = _Gateway()
    channel, thread = _start_channel(gateway)
    try:
        with pytest.raises(HTTPError) as caught:
            _post(
                _bound_port(channel),
                {
                    "channel": "telegram",
                    "session": "spoof",
                    "text": "delete everything",
                },
            )
    finally:
        _stop_channel(channel, thread)

    assert caught.value.code == 400
    assert gateway.calls == []


class _SpeechResponse:
    def iter_bytes(self) -> list[bytes]:
        return [b"\x01\x02", b"\x03\x04"]


class _SpeechContext:
    def __enter__(self) -> _SpeechResponse:
        return _SpeechResponse()

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        return None


class _SpeechEndpoint:
    def __init__(self) -> None:
        self.request: dict[str, str] = {}

    def create(self, **kwargs: str) -> _SpeechContext:
        self.request = kwargs
        return _SpeechContext()


class _Speech:
    def __init__(self) -> None:
        self.with_streaming_response = _SpeechEndpoint()


class _Audio:
    def __init__(self) -> None:
        self.speech = _Speech()


class _OpenAIClient:
    def __init__(self) -> None:
        self.audio = _Audio()


def test_gateway_reply_streams_to_configured_pcm_sink(
    tmp_path: Path,
) -> None:
    gateway_module = _voice_module("birkin.voice.gateway")
    openai_module = _voice_module("birkin.voice.openai_voice")
    audio_module = _voice_module("birkin.voice.audio")

    gateway = _Gateway()
    channel, thread = _start_channel(gateway)
    try:
        client = gateway_module.GatewayClient(
            f"http://127.0.0.1:{_bound_port(channel)}/message",
            session_id="voice-fixed",
        )
        reply = client.send("status")
    finally:
        _stop_channel(channel, thread)

    openai_client = _OpenAIClient()
    tts = openai_module.OpenAITTS(
        client=openai_client,
        model="gpt-4o-mini-tts",
        voice="coral",
        instructions="Speak concisely and clearly.",
    )
    sink_path = tmp_path / "reply.pcm"
    sink = audio_module.PcmFileSink(sink_path)
    sink.write(tts.synthesize(reply))

    assert gateway.calls == [("voice", "voice-fixed", "status")]
    assert reply == "reply:status"
    assert sink_path.read_bytes() == b"\x01\x02\x03\x04"
    assert openai_client.audio.speech.with_streaming_response.request == {
        "model": "gpt-4o-mini-tts",
        "voice": "coral",
        "input": "reply:status",
        "instructions": "Speak concisely and clearly.",
        "response_format": "pcm",
    }
