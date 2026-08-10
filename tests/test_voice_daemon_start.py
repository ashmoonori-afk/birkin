from __future__ import annotations

import argparse
import importlib
import json
import socket
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

import pytest

from birkin.voice.daemon_state import DaemonState


def _daemon_module():
    return importlib.import_module("birkin.voice.daemon")


def test_daemon_start_waits_for_authenticated_readiness(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    daemon = _daemon_module()
    state_path = tmp_path / "daemon.json"
    log_path = tmp_path / "daemon.log"

    @dataclass
    class FakeProcess:
        pid: int = 31337
        terminated: bool = False

        def terminate(self) -> None:
            self.terminated = True

    def launch(
        env: Mapping[str, str],
        target_log: Path,
    ) -> FakeProcess:
        assert target_log == log_path
        readiness = json.loads(env["BIRKIN_VOICE_DAEMON_READY"])
        state = {
            "instance_id": "instance-id",
            "pid": 4242,
            "host": "127.0.0.1",
            "port": 45454,
            "token": "control-token",
            "status": "running",
        }
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with socket.create_connection(
            ("127.0.0.1", readiness["port"]),
            timeout=2.0,
        ) as client:
            payload = {
                "token": readiness["token"],
                "state": state,
            }
            client.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        return FakeProcess()

    result = daemon.start_daemon(
        argparse.Namespace(
            once=False,
            audio=None,
            transcript=None,
            voice_command=None,
            command_audio="",
        ),
        state_path=state_path,
        log_path=log_path,
        launcher=launch,
    )

    assert result == 0
    assert "VOICE_DAEMON_STARTED pid=4242" in capsys.readouterr().out


def test_daemon_start_replaces_stale_state_before_launch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    daemon = _daemon_module()
    state_path = tmp_path / "daemon.json"
    log_path = tmp_path / "daemon.log"
    stale = {
        "instance_id": "stale-instance",
        "pid": 999999,
        "host": "127.0.0.1",
        "port": 9,
        "token": "stale-token",
        "status": "running",
    }
    state_path.write_text(json.dumps(stale), encoding="utf-8")

    @dataclass
    class FakeProcess:
        pid: int = 4242

        def terminate(self) -> None:
            pytest.fail("ready daemon must not be terminated")

    def launch(
        env: Mapping[str, str],
        target_log: Path,
    ) -> FakeProcess:
        assert target_log == log_path
        assert state_path.exists() is False
        readiness = json.loads(env["BIRKIN_VOICE_DAEMON_READY"])
        state = {
            "instance_id": "replacement-instance",
            "pid": 4242,
            "host": "127.0.0.1",
            "port": 45454,
            "token": "replacement-token",
            "status": "running",
        }
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with socket.create_connection(
            ("127.0.0.1", readiness["port"]),
            timeout=2.0,
        ) as client:
            payload = {
                "token": readiness["token"],
                "state": state,
            }
            client.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        return FakeProcess()

    result = daemon.start_daemon(
        argparse.Namespace(
            once=False,
            audio=None,
            transcript=None,
            voice_command=None,
            command_audio="",
        ),
        state_path=state_path,
        log_path=log_path,
        launcher=launch,
    )

    assert result == 0
    assert "VOICE_DAEMON_STARTED pid=4242" in capsys.readouterr().out


def test_live_daemon_state_survives_transient_status_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon = _daemon_module()
    state_path = tmp_path / "daemon.json"
    state = DaemonState(
        instance_id="instance-id",
        token="control-token",
        pid=4242,
        host="127.0.0.1",
        port=45454,
    )
    state_path.write_text(json.dumps(asdict(state)), encoding="utf-8")
    monkeypatch.setattr(
        daemon,
        "request",
        lambda _state, _action: (_ for _ in ()).throw(TimeoutError),
    )
    monkeypatch.setattr(
        daemon,
        "_pid_alive",
        lambda _pid: True,
        raising=False,
    )

    active = daemon._active_state(state_path)

    assert active is not None
    assert active.status == "unreachable"
    assert state_path.exists() is True


def test_daemon_start_reports_authenticated_worker_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    daemon = _daemon_module()
    state_path = tmp_path / "daemon.json"
    log_path = tmp_path / "daemon.log"

    @dataclass
    class FakeProcess:
        pid: int = 4242
        terminated: bool = False

        def terminate(self) -> None:
            self.terminated = True

    process = FakeProcess()

    def launch(
        env: Mapping[str, str],
        target_log: Path,
    ) -> FakeProcess:
        assert target_log == log_path
        readiness = json.loads(env["BIRKIN_VOICE_DAEMON_READY"])
        with socket.create_connection(
            ("127.0.0.1", readiness["port"]),
            timeout=2.0,
        ) as client:
            payload = {
                "token": readiness["token"],
                "error": "voice state is already claimed",
            }
            client.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        return process

    result = daemon.start_daemon(
        argparse.Namespace(
            once=False,
            audio=None,
            transcript=None,
            voice_command=None,
            command_audio="",
        ),
        state_path=state_path,
        log_path=log_path,
        launcher=launch,
    )

    assert result == 1
    assert process.terminated is True
    assert "voice state is already claimed" in capsys.readouterr().err
