from __future__ import annotations

import argparse
import importlib
import json
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest


def _daemon_module():
    return importlib.import_module("birkin.voice.daemon")


def test_daemon_start_ignores_invalid_readiness_peer(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    daemon = _daemon_module()
    state_path = tmp_path / "daemon.json"
    log_path = tmp_path / "daemon.log"

    @dataclass
    class FakeProcess:
        pid: int = 4242

        def terminate(self) -> None:
            pytest.fail("ready daemon must not be terminated")

    def launch(
        env: Mapping[str, str],
        _target_log: Path,
    ) -> FakeProcess:
        readiness = json.loads(env["BIRKIN_VOICE_DAEMON_READY"])
        address = ("127.0.0.1", readiness["port"])
        with socket.create_connection(address, timeout=2.0) as client:
            client.sendall(b'{"token":"wrong"}\n')
        state = {
            "instance_id": "instance-id",
            "pid": 4242,
            "host": "127.0.0.1",
            "port": 45454,
            "token": "control-token",
            "status": "running",
        }
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with socket.create_connection(address, timeout=2.0) as client:
            client.sendall(
                json.dumps(
                    {"token": readiness["token"], "state": state}
                ).encode("utf-8")
                + b"\n"
            )
        return FakeProcess()

    result = daemon.start_daemon(
        argparse.Namespace(
            once=False,
            audio=None,
            transcript=None,
            voice_command=None,
            command_audio="",
            background=False,
        ),
        state_path=state_path,
        log_path=log_path,
        launcher=launch,
    )

    assert result == 0
    assert "VOICE_DAEMON_STARTED pid=4242" in capsys.readouterr().out


def test_daemon_start_ignores_silent_readiness_peer(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    daemon = _daemon_module()
    state_path = tmp_path / "daemon.json"
    log_path = tmp_path / "daemon.log"
    silent: socket.socket | None = None

    @dataclass
    class FakeProcess:
        pid: int = 4242

        def terminate(self) -> None:
            pytest.fail("ready daemon must not be terminated")

    def launch(
        env: Mapping[str, str],
        _target_log: Path,
    ) -> FakeProcess:
        nonlocal silent
        readiness = json.loads(env["BIRKIN_VOICE_DAEMON_READY"])
        address = ("127.0.0.1", readiness["port"])
        silent = socket.create_connection(address, timeout=2.0)
        state = {
            "instance_id": "instance-id",
            "pid": 4242,
            "host": "127.0.0.1",
            "port": 45454,
            "token": "control-token",
            "status": "running",
        }
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with socket.create_connection(address, timeout=2.0) as client:
            client.sendall(
                json.dumps(
                    {"token": readiness["token"], "state": state}
                ).encode("utf-8")
                + b"\n"
            )
        return FakeProcess()

    try:
        result = daemon.start_daemon(
            argparse.Namespace(
                once=False,
                audio=None,
                transcript=None,
                voice_command=None,
                command_audio="",
                background=False,
            ),
            state_path=state_path,
            log_path=log_path,
            launcher=launch,
        )
    finally:
        if silent is not None:
            silent.close()

    assert result == 0
    assert "VOICE_DAEMON_STARTED pid=4242" in capsys.readouterr().out


def test_daemon_start_multiplexes_many_silent_readiness_peers(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    daemon = _daemon_module()
    state_path = tmp_path / "daemon.json"
    log_path = tmp_path / "daemon.log"
    silent: list[socket.socket] = []

    @dataclass
    class FakeProcess:
        pid: int = 4242

        def terminate(self) -> None:
            pytest.fail("ready daemon must not be terminated")

    def launch(
        env: Mapping[str, str],
        _target_log: Path,
    ) -> FakeProcess:
        readiness = json.loads(env["BIRKIN_VOICE_DAEMON_READY"])
        address = ("127.0.0.1", readiness["port"])
        silent.extend(
            socket.create_connection(address, timeout=2.0)
            for _index in range(20)
        )
        state = {
            "instance_id": "instance-id",
            "pid": 4242,
            "host": "127.0.0.1",
            "port": 45454,
            "token": "control-token",
            "status": "running",
        }
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with socket.create_connection(address, timeout=2.0) as client:
            client.sendall(
                json.dumps(
                    {"token": readiness["token"], "state": state}
                ).encode("utf-8")
                + b"\n"
            )
        return FakeProcess()

    try:
        result = daemon.start_daemon(
            argparse.Namespace(
                once=False,
                audio=None,
                transcript=None,
                voice_command=None,
                command_audio="",
                background=False,
            ),
            state_path=state_path,
            log_path=log_path,
            launcher=launch,
        )
    finally:
        for connection in silent:
            connection.close()

    assert result == 0
    assert "VOICE_DAEMON_STARTED pid=4242" in capsys.readouterr().out
