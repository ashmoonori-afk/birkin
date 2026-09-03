"""Web, native bridge, service, and voice command registration."""

from __future__ import annotations

import argparse
from pathlib import Path

from ._types import Handlers


def _web_port(value: str) -> int:
    port = int(value)
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 0 and 65535")
    return port


def register_web_and_bridge(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser], handlers: Handlers
) -> None:
    wp = subparsers.add_parser("web", help="launch the local WebUI")
    wp.add_argument("--port", type=_web_port, default=None)
    wp.add_argument("--no-browser", action="store_true")
    wp.set_defaults(func=handlers["_cmd_web"])

    nbp = subparsers.add_parser(
        "native-bridge",
        help="serve the local bridge the macOS application connects to",
    )
    nb_sub = nbp.add_subparsers(dest="native_bridge_action", required=True)
    nb_serve = nb_sub.add_parser(
        "serve",
        help="serve one authenticated local endpoint until stopped",
    )
    nb_serve.add_argument(
        "--transport",
        choices=("uds", "loopback"),
        default=None,
        help="private Unix socket on POSIX or private loopback on Windows (default)",
    )
    nb_serve.add_argument(
        "--session-id",
        default=None,
        help="workspace session to serve (default: native-app)",
    )
    nb_serve.add_argument(
        "--root",
        type=Path,
        default=None,
        help="bridge state directory (default: $BIRKIN_HOME/native-bridge)",
    )
    nb_serve.set_defaults(func=handlers["_cmd_native_bridge"])
    nb_probe = nb_sub.add_parser(
        "provider-probe",
        help="run one existing-account provider completion for release evidence",
    )
    nb_probe.add_argument("--provider", default="codex-cli", choices=("codex-cli",))
    nb_probe.add_argument("--model", default="default")
    nb_probe.add_argument("--output", type=Path)
    nb_probe.set_defaults(func=handlers["_cmd_native_provider_probe"])


def register_services_and_voice(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser], handlers: Handlers
) -> None:
    subparsers.add_parser("setup", help="guided onboarding wizard").set_defaults(
        func=handlers["_cmd_setup"]
    )
    subparsers.add_parser(
        "onboard", help="alias for setup (first-run wizard)"
    ).set_defaults(func=handlers["_cmd_setup"])

    subparsers.add_parser(
        "gateway",
        help=(
            "run birkin as a service (HTTP / Telegram inbound; "
            "Slack / Discord send-only)"
        ),
    ).set_defaults(func=handlers["_cmd_gateway"])

    p_omo = subparsers.add_parser(
        "omo",
        help="inspect the local OMO-enabled gateway",
    )
    omo_sub = p_omo.add_subparsers(dest="omo_action", required=True)
    omo_sub.add_parser(
        "diagnose",
        help="print secret-free gateway ownership and readiness",
    ).set_defaults(func=handlers["_cmd_omo"])

    p_voice = subparsers.add_parser(
        "voice",
        help="manage the voice daemon or run one deterministic turn",
    )
    p_voice.add_argument(
        "voice_action",
        nargs="?",
        choices=("setup", "onboard", "start", "status", "stop"),
        help="guided setup or daemon lifecycle action",
    )
    p_voice.add_argument(
        "--daemon-worker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    p_voice.add_argument(
        "--once",
        action="store_true",
        help="capture and process exactly one command",
    )
    p_voice.add_argument(
        "--audio",
        help="wake-window 16-bit PCM WAV path",
    )
    p_voice.add_argument(
        "--transcript",
        help="wake transcript (deterministic mode)",
    )
    p_voice.add_argument(
        "--command",
        dest="voice_command",
        help="command text (deterministic mode)",
    )
    p_voice.add_argument(
        "--command-audio",
        default="",
        help="recorded command WAV (transcribed when --command is omitted)",
    )
    p_voice.add_argument(
        "--wake-seconds",
        type=float,
        default=3.0,
        help="live microphone wake-window duration",
    )
    p_voice.add_argument(
        "--command-seconds",
        type=float,
        default=8.0,
        help="live microphone command-window duration",
    )
    p_voice.add_argument(
        "--sample-rate",
        type=int,
        default=None,
        help="live microphone sample rate (default: voice.sample_rate)",
    )
    p_voice.add_argument(
        "--stt-model",
        default=None,
        help="OpenAI speech-to-text model (default: voice.stt_model)",
    )
    p_voice.add_argument(
        "--wake-phrase",
        default=None,
        help="normalized phrase required with the clap (default: voice.wake_phrase)",
    )
    p_voice.add_argument(
        "--gateway-url",
        default=None,
        help="local Birkin POST /message URL (default: voice.gateway_url)",
    )
    p_voice.add_argument(
        "--session-id",
        default=None,
        help="stable local Gateway session id (default: voice.session_id)",
    )
    p_voice.add_argument(
        "--tts-output",
        default="",
        help="write raw PCM16/24 kHz reply bytes to this path",
    )
    p_voice.add_argument(
        "--tts-model",
        default=None,
        help="OpenAI text-to-speech model (default: voice.tts_model)",
    )
    p_voice.add_argument(
        "--tts-voice",
        default=None,
        help="OpenAI text-to-speech voice (default: voice.tts_voice)",
    )
    p_voice.add_argument(
        "--tts-instructions",
        default=None,
        help="OpenAI speech style instructions (default: voice.tts_instructions)",
    )
    p_voice.add_argument(
        "--filler-text",
        default=None,
        help=(
            "short acknowledgement spoken while waiting for the Gateway "
            "(empty disables; default: voice.filler_text)"
        ),
    )
    p_voice.add_argument(
        "--no-playback",
        action="store_true",
        help="do not play synthesized PCM through the speaker",
    )
    p_voice.add_argument(
        "--background",
        action="store_true",
        help="enqueue the command and persist a durable receipt",
    )
    p_voice.add_argument(
        "--receipt-dir",
        default="",
        help="background receipt directory (default: BIRKIN_HOME/voice/jobs)",
    )
    p_voice.add_argument(
        "--background-workers",
        type=int,
        default=None,
        help="maximum workers (default: voice.background_workers)",
    )
    p_voice.add_argument(
        "--background-timeout",
        type=float,
        default=300.0,
        help="seconds to wait for this one-shot background result",
    )
    p_voice.set_defaults(func=handlers["_cmd_voice"])
