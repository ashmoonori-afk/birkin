"""Exercise GPT wake and command transcription through the real CLI."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from birkin.gateway.channels.local_http import LocalHTTPChannel
from script.qa.voice_pipeline_smoke import _Gateway, _SpeechAPI, _write_clap


def main() -> int:
    root = Path(__file__).parents[2]
    gateway = _Gateway()
    channel = LocalHTTPChannel(0)
    gateway_thread = threading.Thread(
        target=channel.start,
        args=(gateway,),
        daemon=True,
    )
    speech_api = _SpeechAPI()
    gateway_thread.start()
    if not channel.wait_until_ready(2.0):
        raise RuntimeError("Gateway HTTP channel did not become ready")
    speech_api.start()

    passed = False
    try:
        with tempfile.TemporaryDirectory(prefix="birkin-stt-qa-") as raw:
            temp = Path(raw)
            wake = temp / "wake.wav"
            command_audio = temp / "command.wav"
            sink = temp / "reply.pcm"
            _write_clap(wake)
            _write_clap(command_audio)

            env = os.environ.copy()
            env["OPENAI_API_KEY"] = "qa-local-key"
            env["OPENAI_BASE_URL"] = speech_api.base_url
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "birkin",
                    "voice",
                    "--once",
                    "--audio",
                    str(wake),
                    "--command-audio",
                    str(command_audio),
                    "--gateway-url",
                    f"http://127.0.0.1:{channel.port}/message",
                    "--session-id",
                    "voice-stt-fixed",
                    "--tts-output",
                    str(sink),
                    "--no-playback",
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=30.0,
                check=False,
            )
            print(f"CLI_EXIT={result.returncode}")
            print(result.stdout.rstrip())
            if result.stderr:
                print(result.stderr.rstrip(), file=sys.stderr)

            stt_ok = speech_api.transcription_count == 2
            command_ok = (
                "WAKE_ACCEPTED" in result.stdout
                and "COMMAND=status" in result.stdout
            )
            gateway_ok = gateway.calls == [
                ("voice", "voice-stt-fixed", "status")
            ]
            tts_ok = (
                speech_api.request.get("input") == "voice-reply:status"
                and sink.read_bytes() == b"\x01\x02\x03\x04"
            )
            print(f"STT_REQUESTS={'PASS' if stt_ok else 'FAIL'}")
            print(f"COMMAND_COLLECTION={'PASS' if command_ok else 'FAIL'}")
            print(f"GATEWAY_ROUTE={'PASS' if gateway_ok else 'FAIL'}")
            print(f"TTS_DELIVERY={'PASS' if tts_ok else 'FAIL'}")
            passed = (
                result.returncode == 0
                and stt_ok
                and command_ok
                and gateway_ok
                and tts_ok
            )
    finally:
        channel.stop()
        gateway_thread.join(timeout=2.0)
        speech_api.stop()

    cleanup = not gateway_thread.is_alive() and not speech_api.thread.is_alive()
    print(f"CLEANUP={'PASS' if cleanup else 'FAIL'}")
    return 0 if passed and cleanup else 1


if __name__ == "__main__":
    raise SystemExit(main())
