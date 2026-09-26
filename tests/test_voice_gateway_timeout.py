"""Voice Gateway client must outlast one Gateway turn and explain timeouts."""

from __future__ import annotations

import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
from birkin.cli import build_parser
from birkin.voice import controller
from birkin.voice.audio import AudioData
from birkin.voice.config import VoiceConfig
from birkin.voice.gateway import GatewayClient, GatewayVoiceError

# Default ``cli_timeout``: how long one Gateway turn may legitimately run.
_GATEWAY_TURN_SECONDS = 300


def test_voice_gateway_timeout_defaults_outlast_gateway_turn() -> None:
    parsed = VoiceConfig.from_mapping({})

    assert parsed.gateway_timeout_seconds > _GATEWAY_TURN_SECONDS
    assert (
        GatewayClient(
            "http://127.0.0.1:8788/message",
            session_id="voice-fixed",
        ).timeout_seconds
        > _GATEWAY_TURN_SECONDS
    )


def test_voice_gateway_timeout_is_configurable_and_survives_overrides() -> None:
    parsed = VoiceConfig.from_mapping({"gateway_timeout_seconds": 600})
    overridden = parsed.with_overrides(
        wake_phrase=None,
        gateway_url=None,
        session_id=None,
        sample_rate=None,
        stt_model=None,
        tts_model=None,
        tts_voice=None,
        tts_instructions=None,
        filler_text=None,
        background_workers=None,
    )

    assert parsed.gateway_timeout_seconds == 600
    assert overridden.gateway_timeout_seconds == 600


@pytest.mark.parametrize("value", [0, -1, True, "600"])
def test_voice_gateway_timeout_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValueError, match="gateway_timeout_seconds"):
        VoiceConfig.from_mapping({"gateway_timeout_seconds": value})


def test_gateway_client_timeout_is_reported_in_korean() -> None:
    # A listener that never accepts: the request is sent, no reply arrives.
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        client = GatewayClient(
            f"http://127.0.0.1:{server.getsockname()[1]}/message",
            session_id="voice-fixed",
            timeout_seconds=0.2,
        )
        with pytest.raises(GatewayVoiceError) as caught:
            client.send("status")
    finally:
        server.close()

    message = str(caught.value)
    assert "timed out" not in message
    assert "시간이 초과" in message
    assert isinstance(caught.value.__cause__, TimeoutError)


@pytest.mark.parametrize("background", [False, True])
def test_voice_controller_passes_configured_gateway_timeout(
    background: bool,
    tmp_path: Path,
    monkeypatch,
) -> None:
    constructed: list[dict[str, object]] = []

    class _WakeGate:
        def __init__(self, _config: object) -> None:
            pass

        def has_clap(self, *_args: object, **_kwargs: object) -> bool:
            return True

        def evaluate(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(accepted=True, reason="accepted")

    class _GatewayClient:
        def __init__(self, *_args: object, **kwargs: object) -> None:
            constructed.append(kwargs)

        def send(self, command: str) -> str:
            return f"reply:{command}"

    monkeypatch.setattr(
        controller.config,
        "load_config",
        lambda: {
            "voice": {
                "filler_text": "",
                "gateway_timeout_seconds": 450,
            }
        },
    )
    monkeypatch.setattr(
        controller,
        "read_wav_mono",
        lambda _path: AudioData((1.0,), 24_000),
    )
    monkeypatch.setattr(controller, "WakeGate", _WakeGate)
    monkeypatch.setattr(controller, "GatewayClient", _GatewayClient)
    argv = [
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
        "--no-playback",
    ]
    if background:
        argv += ["--background", "--receipt-dir", str(tmp_path / "jobs")]

    assert controller.run_once(build_parser().parse_args(argv)) == 0
    assert len(constructed) == 1
    assert constructed[0]["timeout_seconds"] == 450


def test_background_wait_outlasts_the_gateway_and_times_out_in_korean(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    waited: list[object] = []

    class _WakeGate:
        def __init__(self, _config: object) -> None:
            pass

        def has_clap(self, *_args: object, **_kwargs: object) -> bool:
            return True

        def evaluate(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(accepted=True, reason="accepted")

    class _GatewayClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def send(self, command: str) -> str:
            return f"reply:{command}"

    def slow_wait(self, job_id: str, timeout: object = None) -> object:
        waited.append(timeout)
        raise TimeoutError(f"background job {job_id} timed out")

    monkeypatch.setattr(
        controller.config,
        "load_config",
        lambda: {"voice": {"filler_text": "", "gateway_timeout_seconds": 450}},
    )
    monkeypatch.setattr(
        controller, "read_wav_mono", lambda _path: AudioData((1.0,), 24_000)
    )
    monkeypatch.setattr(controller, "WakeGate", _WakeGate)
    monkeypatch.setattr(controller, "GatewayClient", _GatewayClient)
    monkeypatch.setattr(controller.BackgroundBroker, "wait", slow_wait)
    argv = [
        "voice", "--once", "--audio", "wake.wav",
        "--transcript", "Daddy is home", "--command", "status",
        "--gateway-url", "http://127.0.0.1:8788/message", "--no-playback",
        "--background", "--receipt-dir", str(tmp_path / "jobs"),
    ]

    assert controller.run_once(build_parser().parse_args(argv)) == 1
    assert waited == [480]                         # gateway timeout + margin
    err = capsys.readouterr().err
    assert "시간이 초과" in err and "timed out" not in err
