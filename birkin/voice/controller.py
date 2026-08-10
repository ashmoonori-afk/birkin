"""One-shot voice orchestration over Birkin's existing Gateway."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from wave import Error as WaveError

from openai import OpenAIError

from .. import config
from ..background import BackgroundBroker
from .audio import (
    AudioData,
    PcmFileSink,
    PcmSpeaker,
    capture_microphone,
    read_wav_mono,
)
from .config import VoiceConfig
from .gateway import GatewayClient, GatewayVoiceError
from .mission import AudioSink, VoiceMissionService
from .openai_voice import OpenAISTT, OpenAITTS
from .wake import WakeConfig, WakeGate


def _options(args: argparse.Namespace) -> VoiceConfig:
    values = config.load_config().get("voice", {})
    if not isinstance(values, dict):
        raise TypeError("voice config must be an object")
    return VoiceConfig.from_mapping(values).with_overrides(
        wake_phrase=args.wake_phrase,
        gateway_url=args.gateway_url,
        session_id=args.session_id,
        sample_rate=args.sample_rate,
        stt_model=args.stt_model,
        tts_model=args.tts_model,
        tts_voice=args.tts_voice,
        tts_instructions=args.tts_instructions,
        background_workers=args.background_workers,
    )


def _capture_wake(
    args: argparse.Namespace,
    options: VoiceConfig,
    stt: OpenAISTT | None,
) -> tuple[AudioData, str]:
    audio = (
        read_wav_mono(args.audio)
        if args.audio
        else capture_microphone(
            duration_seconds=args.wake_seconds,
            sample_rate=options.sample_rate,
        )
    )
    transcript = args.transcript
    if not transcript:
        if stt is None:
            raise RuntimeError("STT client is unavailable")
        transcript = (
            stt.transcribe_path(args.audio)
            if args.audio
            else stt.transcribe_audio(audio)
        )
    return audio, transcript


def _capture_command(
    args: argparse.Namespace,
    options: VoiceConfig,
    stt: OpenAISTT | None,
) -> str:
    command = args.voice_command
    if command:
        return command
    if stt is None:
        raise RuntimeError("STT client is unavailable")
    if args.command_audio:
        return stt.transcribe_path(args.command_audio)
    audio = capture_microphone(
        duration_seconds=args.command_seconds,
        sample_rate=options.sample_rate,
    )
    return stt.transcribe_audio(audio)


def _audio_delivery(
    args: argparse.Namespace,
    options: VoiceConfig,
) -> tuple[OpenAITTS | None, list[AudioSink]]:
    sinks: list[AudioSink] = []
    if args.tts_output:
        sinks.append(PcmFileSink(Path(args.tts_output)))
    if not args.no_playback:
        sinks.append(PcmSpeaker())
    tts = (
        OpenAITTS(
            model=options.tts_model,
            voice=options.tts_voice,
            instructions=options.tts_instructions,
        )
        if sinks
        else None
    )
    return tts, sinks


def _run_background(
    args: argparse.Namespace,
    options: VoiceConfig,
    command: str,
) -> int:
    receipt_dir = (
        Path(args.receipt_dir)
        if args.receipt_dir
        else config.birkin_home() / "voice" / "jobs"
    )
    tts, sinks = _audio_delivery(args, options)
    broker = BackgroundBroker(
        receipt_dir,
        max_workers=options.background_workers,
    )
    wait_for_shutdown = True
    try:
        mission = VoiceMissionService(
            broker,
            GatewayClient(
                options.gateway_url,
                session_id=options.session_id,
                token=os.environ.get("BIRKIN_HTTP_TOKEN", ""),
            ),
            tts=tts,
            sinks=sinks,
        )
        job = mission.submit(command)
        receipt = receipt_dir / f"{job.id}.json"
        print("FOREGROUND_ACK=queued", flush=True)
        print(f"BACKGROUND_RECEIPT={receipt}", flush=True)
        try:
            done = broker.wait(job.id, timeout=args.background_timeout)
        except TimeoutError:
            wait_for_shutdown = False
            raise
    finally:
        broker.close(wait=wait_for_shutdown)

    print(f"BACKGROUND_STATUS={done.status}")
    if done.result:
        print(f"BACKGROUND_RESULT={done.result}")
    return 0 if done.status == "succeeded" else 1


def _run_foreground(
    args: argparse.Namespace,
    options: VoiceConfig,
    command: str,
) -> int:
    reply = GatewayClient(
        options.gateway_url,
        session_id=options.session_id,
        token=os.environ.get("BIRKIN_HTTP_TOKEN", ""),
    ).send(command)
    print(f"REPLY={reply}")

    tts, sinks = _audio_delivery(args, options)
    if tts is None:
        return 0
    pcm = tts.synthesize(reply)
    for sink in sinks:
        sink.write(pcm)
    if args.tts_output:
        print(f"TTS_SAVED={args.tts_output}")
    return 0


def run_once(args: argparse.Namespace) -> int:
    """Capture, gate, route, and optionally speak one voice command."""
    if not args.once:
        print("VOICE_ERROR --once is required", file=sys.stderr)
        return 2

    try:
        options = _options(args)
        stt = (
            OpenAISTT(model=options.stt_model)
            if not args.transcript or not args.voice_command
            else None
        )
        audio, transcript = _capture_wake(args, options, stt)
        decision = WakeGate(
            WakeConfig(wake_phrase=options.wake_phrase)
        ).evaluate(
            audio.samples,
            sample_rate=audio.sample_rate,
            transcript=transcript,
        )
    except (
        OSError,
        OpenAIError,
        RuntimeError,
        TypeError,
        ValueError,
        WaveError,
    ) as exc:
        print(f"VOICE_ERROR {exc}", file=sys.stderr)
        return 1

    if not decision.accepted:
        print(f"WAKE_REJECTED reason={decision.reason}")
        return 2

    try:
        command = _capture_command(args, options, stt)
    except (OSError, OpenAIError, RuntimeError, ValueError, WaveError) as exc:
        print(f"VOICE_ERROR {exc}", file=sys.stderr)
        return 1

    print("WAKE_ACCEPTED")
    print(f"COMMAND={command}")
    if not options.gateway_url:
        return 0

    try:
        if args.background:
            return _run_background(args, options, command)
        return _run_foreground(args, options, command)
    except (
        GatewayVoiceError,
        OpenAIError,
        OSError,
        RuntimeError,
        TimeoutError,
        ValueError,
    ) as exc:
        print(f"VOICE_ERROR {exc}", file=sys.stderr)
        return 1
