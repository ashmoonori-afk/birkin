"""Exercise immediate voice ACK, background receipt, delivery, and safety."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path

from birkin.gateway import core as gateway_core
from birkin.gateway.channels.local_http import LocalHTTPChannel

from voice_pipeline_smoke import _SpeechAPI, _write_clap


class _BlockingGateway:
    pending_hard_restart = False

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple[str, str, str]] = []

    def handle(self, channel: str, session_id: str, text: str) -> str:
        self.calls.append((channel, session_id, text))
        self.entered.set()
        if not self.release.wait(timeout=10.0):
            raise RuntimeError("background QA release was not signalled")
        return f"background-reply:{text}"


def _approval_probe() -> bool:
    observed: list[tuple[bool, bool]] = []
    context = types.SimpleNamespace(
        subagent_approval_required=False,
        approved_work=False,
    )
    agent = types.SimpleNamespace(messages=[])

    def ask(text, **_kwargs):
        observed.append(
            (
                context.subagent_approval_required,
                context.approved_work,
            )
        )
        agent.messages.append(
            {"role": "user", "content": [{"type": "text", "text": text}]}
        )
        return "approval required"

    session = types.SimpleNamespace(
        cfg={},
        agent=agent,
        ask=ask,
        ctx=context,
    )
    original = gateway_core.build_session
    gateway_core.build_session = lambda _cfg: session
    try:
        gateway = gateway_core.Gateway({"gateway_persistent": False})
        reply = gateway.handle(
            "voice",
            "voice-fixed",
            "delete every project",
        )
    finally:
        gateway_core.build_session = original
    return reply == "approval required" and observed == [(False, False)]


def main() -> int:
    root = Path(__file__).parents[2]
    gateway = _BlockingGateway()
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

    process: subprocess.Popen[str] | None = None
    reader: threading.Thread | None = None
    passed = False
    try:
        with tempfile.TemporaryDirectory(prefix="birkin-background-qa-") as raw:
            temp = Path(raw)
            wake = temp / "wake.wav"
            sink = temp / "reply.pcm"
            receipts = temp / "receipts"
            _write_clap(wake)

            env = os.environ.copy()
            env["BIRKIN_HOME"] = str(temp / "home")
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
                "--background",
                "--receipt-dir",
                str(receipts),
                "--background-timeout",
                "20",
            ]
            process = subprocess.Popen(
                command,
                cwd=root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert process.stdout is not None
            output: queue.Queue[str] = queue.Queue()
            ack_seen = threading.Event()
            receipt_seen = threading.Event()
            receipt_path: list[Path] = []

            def read_output() -> None:
                assert process is not None and process.stdout is not None
                for raw_line in process.stdout:
                    line = raw_line.rstrip()
                    output.put(line)
                    print(line)
                    if line == "FOREGROUND_ACK=queued":
                        ack_seen.set()
                    if line.startswith("BACKGROUND_RECEIPT="):
                        receipt_path.append(Path(line.split("=", 1)[1]))
                        receipt_seen.set()

            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()
            immediate = (
                ack_seen.wait(timeout=20.0)
                and receipt_seen.wait(timeout=5.0)
                and process.poll() is None
            )
            print(f"FOREGROUND_ACK={'PASS' if immediate else 'FAIL'}")

            receipt_exists = bool(receipt_path and receipt_path[0].is_file())
            print(
                f"BACKGROUND_RECEIPT={'PASS' if receipt_exists else 'FAIL'}"
            )
            if not gateway.entered.wait(timeout=20.0):
                raise RuntimeError("background CLI did not reach the Gateway")
            gateway.release.set()
            return_code = process.wait(timeout=30.0)
            reader.join(timeout=2.0)
            assert process.stderr is not None
            error_output = process.stderr.read().strip()
            if error_output:
                print(error_output, file=sys.stderr)

            receipt = json.loads(
                receipt_path[0].read_text(encoding="utf-8")
            )
            delivery = (
                return_code == 0
                and receipt["status"] == "succeeded"
                and receipt["result"] == "background-reply:status"
                and sink.read_bytes() == b"\x01\x02\x03\x04"
            )
            safety = _approval_probe()
            print(f"BACKGROUND_DELIVERY={'PASS' if delivery else 'FAIL'}")
            print(f"VOICE_APPROVAL_BYPASS={'PASS' if safety else 'FAIL'}")
            passed = immediate and receipt_exists and delivery and safety
    finally:
        gateway.release.set()
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)
        if reader is not None:
            reader.join(timeout=2.0)
        channel.stop()
        gateway_thread.join(timeout=2.0)
        speech_api.stop()

    cleanup = (
        not gateway_thread.is_alive()
        and not speech_api.thread.is_alive()
        and (process is None or process.poll() is not None)
        and (reader is None or not reader.is_alive())
    )
    print(f"CLEANUP={'PASS' if cleanup else 'FAIL'}")
    return 0 if passed and cleanup else 1


if __name__ == "__main__":
    raise SystemExit(main())
