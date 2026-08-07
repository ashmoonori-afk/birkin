"""Exercise wake -> Gateway -> OpenAI TTS -> PCM sink end to end."""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from birkin.gateway.channels.local_http import LocalHTTPChannel


class _Gateway:
    pending_hard_restart = False

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def handle(self, channel: str, session_id: str, text: str) -> str:
        self.calls.append((channel, session_id, text))
        return f"voice-reply:{text}"


class _SpeechAPI:
    def __init__(self) -> None:
        self.request: dict[str, object] = {}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return None

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                owner.request = json.loads(self.rfile.read(length))
                body = b"\x01\x02\x03\x04"
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )

    @property
    def base_url(self) -> str:
        port = int(self.server.server_address[1])
        return f"http://127.0.0.1:{port}/v1"

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)
        if self.thread.is_alive():
            raise RuntimeError("fake speech API thread did not stop")


def _write_clap(path: Path) -> None:
    samples = [0] * 1_000
    samples[400] = 32_767
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(1_000)
        stream.writeframes(struct.pack("<1000h", *samples))


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

    try:
        with tempfile.TemporaryDirectory(prefix="birkin-voice-qa-") as raw:
            temp = Path(raw)
            wake = temp / "wake.wav"
            sink = temp / "reply.pcm"
            _write_clap(wake)

            env = os.environ.copy()
            env["OPENAI_API_KEY"] = "qa-local-key"
            env["OPENAI_BASE_URL"] = speech_api.base_url
            command = [
                sys.executable,
                "-m",
                "birkin",
                "voice",
                "--once",
                "--audio",
                str(wake),
                "--transcript",
                "Daddy is home",
                "--command",
                "status",
                "--gateway-url",
                f"http://127.0.0.1:{channel.port}/message",
                "--session-id",
                "voice-fixed",
                "--tts-output",
                str(sink),
                "--no-playback",
            ]
            result = subprocess.run(
                command,
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

            gateway_ok = gateway.calls == [
                ("voice", "voice-fixed", "status")
            ]
            tts_ok = speech_api.request == {
                "model": "gpt-4o-mini-tts",
                "voice": "coral",
                "input": "voice-reply:status",
                "instructions": "Speak concisely and clearly.",
                "response_format": "pcm",
            }
            sink_ok = sink.read_bytes() == b"\x01\x02\x03\x04"
            print(f"GATEWAY_CALL={'PASS' if gateway_ok else 'FAIL'}")
            print(f"TTS_REQUEST={'PASS' if tts_ok else 'FAIL'}")
            print(f"PCM_SINK={'PASS' if sink_ok else 'FAIL'}")
            passed = result.returncode == 0 and gateway_ok and tts_ok and sink_ok
    finally:
        channel.stop()
        gateway_thread.join(timeout=2.0)
        speech_api.stop()

    cleanup_ok = not gateway_thread.is_alive() and not speech_api.thread.is_alive()
    print(f"CLEANUP={'PASS' if cleanup_ok else 'FAIL'}")
    return 0 if passed and cleanup_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
