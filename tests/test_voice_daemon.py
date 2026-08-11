from __future__ import annotations

import argparse
import importlib
import queue
import threading
from pathlib import Path
from types import TracebackType

import pytest

from birkin.cli import build_parser
from birkin.voice.daemon_state import DaemonState


def _daemon_module():
    return importlib.import_module("birkin.voice.daemon")


def _daemon_worker_module():
    return importlib.import_module("birkin.voice.daemon_worker")


def test_voice_parser_accepts_daemon_lifecycle_actions() -> None:
    parser = build_parser()

    for action in ("start", "status", "stop"):
        args = parser.parse_args(["voice", action])
        assert args.voice_action == action


def test_voice_parser_preserves_deterministic_once() -> None:
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
        ]
    )

    assert args.voice_action is None
    assert args.once is True
    assert args.voice_command == "status"


def test_daemon_status_and_stop_use_authenticated_control(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    daemon = _daemon_module()
    daemon_worker = _daemon_worker_module()
    state_path = tmp_path / "daemon.json"
    ready: queue.Queue[DaemonState] = queue.Queue()
    turn_started = threading.Event()
    release_turn = threading.Event()

    def run_turn(args: argparse.Namespace) -> int:
        turn_started.set()
        assert release_turn.wait(timeout=10.0)
        return 0

    worker = threading.Thread(
        target=daemon_worker.serve,
        kwargs={
            "args": argparse.Namespace(),
            "state_path": state_path,
            "ready": ready.put,
            "run_turn": run_turn,
        },
    )
    worker.start()
    state = ready.get(timeout=10.0)
    assert turn_started.wait(timeout=10.0)

    assert daemon.status_daemon(state_path=state_path) == 0
    stop_result: queue.Queue[int] = queue.Queue()

    def stop() -> None:
        stop_result.put(daemon.stop_daemon(state_path=state_path))

    stopper = threading.Thread(target=stop)
    stopper.start()
    release_turn.set()
    assert stop_result.get(timeout=10.0) == 0
    stopper.join(timeout=10.0)
    worker.join(timeout=10.0)

    assert stopper.is_alive() is False
    assert worker.is_alive() is False
    assert state_path.exists() is False
    assert f"VOICE_DAEMON_RUNNING pid={state.pid}" in capsys.readouterr().out


def test_daemon_stop_waits_for_the_current_bounded_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon_state = importlib.import_module("birkin.voice.daemon_state")
    response_timeouts: list[float] = []

    class Response:
        def readline(self, _limit: int) -> bytes:
            return b'{"status":"stopped"}\n'

    class Client:
        def __enter__(self) -> Client:
            return self

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _traceback: TracebackType | None,
        ) -> None:
            return None

        def settimeout(self, timeout: float) -> None:
            response_timeouts.append(timeout)

        def sendall(self, _payload: bytes) -> None:
            return None

        def makefile(self, _mode: str) -> Response:
            return Response()

    def connect(
        _address: tuple[str, int],
        *,
        timeout: float,
    ) -> Client:
        assert timeout == 2.0
        return Client()

    monkeypatch.setattr(daemon_state.socket, "create_connection", connect)
    state = daemon_state.DaemonState(
        instance_id="instance-id",
        token="control-token",
        pid=4242,
        host="127.0.0.1",
        port=45454,
    )

    assert daemon_state.request(state, "STOP") == "stopped"
    assert response_timeouts == [32.0]
