from __future__ import annotations

import importlib
import importlib.util
import json
import socket
import threading
from http.client import HTTPConnection
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from openai import OpenAIError

from birkin.cli import build_parser
from birkin.gateway.channels.local_http import LocalHTTPChannel
from birkin.gateway.core import Gateway as BirkinGateway
from birkin.voice.audio import AudioData


class _Gateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.pending_hard_restart = False

    def handle(self, channel: str, session_id: str, text: str) -> str:
        self.calls.append((channel, session_id, text))
        return f"reply:{text}"


def _post(port: int, body: dict[str, object]) -> tuple[int, dict[str, str]]:
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
    gateway: _Gateway | BirkinGateway,
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


@pytest.mark.parametrize("channel_value", [[], {}])
def test_local_http_rejects_non_string_channel(
    channel_value: object,
) -> None:
    gateway = _Gateway()
    channel, thread = _start_channel(gateway)
    try:
        with pytest.raises(HTTPError) as caught:
            _post(
                _bound_port(channel),
                {
                    "channel": channel_value,
                    "session": "invalid",
                    "text": "status",
                },
            )
    finally:
        _stop_channel(channel, thread)

    assert caught.value.code == 400
    assert gateway.calls == []


@pytest.mark.parametrize("text_value", [[], {}, 1])
def test_local_http_rejects_non_string_text(text_value: object) -> None:
    gateway = _Gateway()
    channel, thread = _start_channel(gateway)
    try:
        with pytest.raises(HTTPError) as caught:
            _post(
                _bound_port(channel),
                {
                    "channel": "voice",
                    "session": "invalid",
                    "text": text_value,
                },
            )
    finally:
        _stop_channel(channel, thread)

    assert caught.value.code == 400
    assert gateway.calls == []


def test_local_http_rejects_oversized_body() -> None:
    gateway = _Gateway()
    channel, thread = _start_channel(gateway)
    connection = HTTPConnection("127.0.0.1", _bound_port(channel), timeout=2.0)
    try:
        connection.putrequest("POST", "/message")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", "1000001")
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 413
    finally:
        connection.close()
        _stop_channel(channel, thread)

    assert gateway.calls == []


def test_local_http_times_out_incomplete_body() -> None:
    gateway = _Gateway()
    channel, thread = _start_channel(gateway)
    try:
        with socket.create_connection(
            ("127.0.0.1", _bound_port(channel)),
            timeout=2.0,
        ) as client:
            client.settimeout(4.0)
            client.sendall(
                b"POST /message HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: 10\r\n"
                b"Connection: close\r\n"
                b"\r\n"
                b"{"
            )
            response = client.recv(4096)
    finally:
        _stop_channel(channel, thread)

    assert response.startswith(b"HTTP/1.0 408")
    assert gateway.calls == []


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/birkin.sock",
        "https://127.0.0.1:8765/message",
        "http://example.com/message",
    ],
)
def test_gateway_client_rejects_non_loopback_http_endpoints(url: str) -> None:
    gateway_module = _voice_module("birkin.voice.gateway")

    with pytest.raises(ValueError, match="loopback HTTP"):
        gateway_module.GatewayClient(url, session_id="voice-fixed")


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


def test_voice_controller_normalizes_tts_api_errors(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    controller = importlib.import_module("birkin.voice.controller")

    class _WakeGate:
        def __init__(self, _config: object) -> None:
            pass

        def evaluate(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(accepted=True, reason="accepted")

    class _GatewayClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def send(self, _command: str) -> str:
            return "reply:status"

    class _OpenAITTS:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def synthesize(self, _reply: str) -> bytes:
            raise OpenAIError("quota")

    monkeypatch.setattr(
        controller,
        "read_wav_mono",
        lambda _path: AudioData((1.0,), 24_000),
    )
    monkeypatch.setattr(controller, "WakeGate", _WakeGate)
    monkeypatch.setattr(controller, "GatewayClient", _GatewayClient)
    monkeypatch.setattr(controller, "OpenAITTS", _OpenAITTS)
    args = build_parser().parse_args(
        [
            "voice",
            "--once",
            "--audio",
            "wake.wav",
            "--transcript",
            "Daddy is home",
            "--command",
            "status",
            "--gateway-url",
            "http://127.0.0.1:8788/message",
            "--tts-output",
            str(tmp_path / "reply.pcm"),
            "--no-playback",
        ]
    )

    assert controller.run_once(args) == 1
    assert "VOICE_ERROR quota" in capsys.readouterr().err


@pytest.mark.parametrize("provider", ["claude-cli", "codex-cli"])
def test_voice_controller_starts_filler_while_oauth_gateway_is_pending(
    provider: str,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from birkin.gateway import core as gateway_core

    controller = importlib.import_module("birkin.voice.controller")
    gateway_started = threading.Event()
    release_reply = threading.Event()
    filler_started = threading.Event()
    providers: list[str] = []
    synthesized: list[str] = []
    result: list[int] = []

    class _WakeGate:
        def __init__(self, _config: object) -> None:
            pass

        def evaluate(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(accepted=True, reason="accepted")

    def ask(text: str, **_kwargs: object) -> str:
        gateway_started.set()
        if not release_reply.wait(2.0):
            raise TimeoutError("test did not release the OAuth Gateway reply")
        return f"reply:{text}"

    agent = SimpleNamespace(messages=[])
    session = SimpleNamespace(
        cfg={},
        agent=agent,
        ask=ask,
        ctx=SimpleNamespace(
            subagent_approval_required=False,
            approved_work=False,
        ),
    )

    def build_session(cfg: dict[str, object]) -> object:
        providers.append(str(cfg["provider"]))
        return session

    class _OpenAITTS:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def synthesize(self, text: str) -> bytes:
            synthesized.append(text)
            if text == "On it.":
                filler_started.set()
            return b"\x01\x02"

    monkeypatch.setattr(gateway_core, "build_session", build_session)
    monkeypatch.setattr(
        controller.config,
        "load_config",
        lambda: {"voice": {"filler_text": "On it."}},
    )
    monkeypatch.setattr(
        controller,
        "read_wav_mono",
        lambda _path: AudioData((1.0,), 24_000),
    )
    monkeypatch.setattr(controller, "WakeGate", _WakeGate)
    monkeypatch.setattr(controller, "OpenAITTS", _OpenAITTS)

    gateway = gateway_core.Gateway(
        {"provider": provider, "gateway_persistent": False}
    )
    channel, channel_thread = _start_channel(gateway)
    args = build_parser().parse_args(
        [
            "voice",
            "--once",
            "--audio",
            "wake.wav",
            "--transcript",
            "Daddy is home",
            "--command",
            "status",
            "--gateway-url",
            f"http://127.0.0.1:{_bound_port(channel)}/message",
            "--tts-output",
            str(tmp_path / "reply.pcm"),
            "--no-playback",
        ]
    )
    voice_thread = threading.Thread(
        target=lambda: result.append(controller.run_once(args)),
        daemon=True,
    )
    voice_thread.start()
    try:
        assert gateway_started.wait(2.0)
        assert filler_started.wait(2.0)
        assert voice_thread.is_alive()
    finally:
        release_reply.set()
        voice_thread.join(timeout=2.0)
        _stop_channel(channel, channel_thread)

    assert not voice_thread.is_alive()
    assert result == [0]
    assert providers == [provider]
    assert synthesized == ["On it.", "reply:status"]
    output = capsys.readouterr().out
    assert output.index("FILLER=On it.") < output.index("REPLY=reply:status")


def test_voice_controller_empty_filler_keeps_final_reply(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    controller = importlib.import_module("birkin.voice.controller")
    synthesized: list[str] = []

    class _WakeGate:
        def __init__(self, _config: object) -> None:
            pass

        def evaluate(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(accepted=True, reason="accepted")

    class _GatewayClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def send(self, command: str) -> str:
            return f"reply:{command}"

    class _OpenAITTS:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def synthesize(self, text: str) -> bytes:
            synthesized.append(text)
            return b"\x01\x02"

    monkeypatch.setattr(
        controller.config,
        "load_config",
        lambda: {"voice": {"filler_text": "On it."}},
    )
    monkeypatch.setattr(
        controller,
        "read_wav_mono",
        lambda _path: AudioData((1.0,), 24_000),
    )
    monkeypatch.setattr(controller, "WakeGate", _WakeGate)
    monkeypatch.setattr(controller, "GatewayClient", _GatewayClient)
    monkeypatch.setattr(controller, "OpenAITTS", _OpenAITTS)
    args = build_parser().parse_args(
        [
            "voice",
            "--once",
            "--audio",
            "wake.wav",
            "--transcript",
            "Daddy is home",
            "--command",
            "status",
            "--gateway-url",
            "http://127.0.0.1:8788/message",
            "--tts-output",
            str(tmp_path / "reply.pcm"),
            "--no-playback",
            "--filler-text",
            "",
        ]
    )

    assert controller.run_once(args) == 0
    assert synthesized == ["reply:status"]
    output = capsys.readouterr().out
    assert "FILLER=" not in output
    assert "REPLY=reply:status" in output
