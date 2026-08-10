"""Detached voice daemon worker runtime."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Final
from uuid import uuid4

from .daemon_control import control_loop
from .daemon_state import (
    DaemonState,
    create_control_listener,
)
from .daemon_storage import (
    claim_state,
    daemon_paths,
    remove_state,
)

READY_ENV: Final = "BIRKIN_VOICE_DAEMON_READY"
OPTIONS_ENV: Final = "BIRKIN_VOICE_DAEMON_OPTIONS"
READY_TIMEOUT_SECONDS: Final = 5.0
VOICE_ARGUMENTS: Final = (
    "audio",
    "transcript",
    "voice_command",
    "command_audio",
    "wake_seconds",
    "command_seconds",
    "sample_rate",
    "stt_model",
    "wake_phrase",
    "gateway_url",
    "session_id",
    "tts_output",
    "tts_model",
    "tts_voice",
    "tts_instructions",
    "no_playback",
    "background",
    "receipt_dir",
    "background_workers",
    "background_timeout",
)
TurnRunner = Callable[[argparse.Namespace], int]


def serve(
    args: argparse.Namespace,
    *,
    state_path: Path | None = None,
    ready: Callable[[DaemonState], None] | None = None,
    run_turn: TurnRunner | None = None,
) -> int:
    """Run voice turns until an authenticated stop request arrives."""
    state_path = state_path or daemon_paths()[0]
    listener = create_control_listener()
    state = DaemonState(
        instance_id=uuid4().hex,
        token=secrets.token_urlsafe(32),
        pid=os.getpid(),
        host="127.0.0.1",
        port=listener.getsockname()[1],
    )
    stop_requested = threading.Event()
    stopped = threading.Event()
    controller = threading.Thread(
        target=control_loop,
        args=(
            listener,
            state_path,
            state,
            stop_requested,
            stopped,
        ),
        name="birkin-voice-control",
        daemon=True,
    )
    try:
        claim_state(state_path, state)
        controller.start()
        (ready or _notify_ready)(state)
        args.once = True
        if run_turn is None:
            from .controller import run_once

            run_turn = run_once
        while not stop_requested.is_set():
            result = run_turn(args)
            if result not in {0, 2}:
                return result
        return 0
    finally:
        remove_state(state_path, state.instance_id)
        stopped.set()
        listener.close()
        if controller.is_alive():
            controller.join(timeout=2.0)


def run_worker(args: argparse.Namespace) -> int:
    """Restore daemon options and run the worker boundary."""
    try:
        _restore_options(args)
        return serve(args)
    except (
        FileExistsError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        _notify_error(str(exc))
        print(f"VOICE_DAEMON_ERROR {exc}", file=sys.stderr)
        return 1


def _restore_options(args: argparse.Namespace) -> None:
    value = json.loads(os.environ[OPTIONS_ENV])
    if not isinstance(value, dict):
        raise TypeError("voice daemon options must be an object")
    for name in VOICE_ARGUMENTS:
        setattr(args, name, value.get(name))


def _notify_ready(state: DaemonState) -> None:
    value = json.loads(os.environ[READY_ENV])
    if not isinstance(value, dict):
        raise TypeError("voice daemon readiness must be an object")
    payload = {"token": value.get("token"), "state": asdict(state)}
    with socket.create_connection(
        ("127.0.0.1", int(value["port"])),
        timeout=READY_TIMEOUT_SECONDS,
    ) as client:
        client.sendall(json.dumps(payload).encode("utf-8") + b"\n")


def _notify_error(message: str) -> None:
    try:
        value = json.loads(os.environ[READY_ENV])
        payload = {"token": value.get("token"), "error": message}
        with socket.create_connection(
            ("127.0.0.1", int(value["port"])),
            timeout=READY_TIMEOUT_SECONDS,
        ) as client:
            client.sendall(
                json.dumps(payload).encode("utf-8") + b"\n"
            )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return
