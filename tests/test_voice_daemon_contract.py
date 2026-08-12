from __future__ import annotations

import argparse
import importlib
from pathlib import Path

import pytest
from openai import OpenAIError

from birkin.cli import build_parser
from birkin.voice.daemon_state import DaemonState


def _daemon_module():
    return importlib.import_module("birkin.voice.daemon")


def _daemon_worker_module():
    return importlib.import_module("birkin.voice.daemon_worker")


def test_daemon_start_reports_stopping_instance(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon = _daemon_module()
    state = DaemonState(
        instance_id="instance-id",
        token="control-token",
        pid=4242,
        host="127.0.0.1",
        port=45454,
        status="stopping",
    )
    monkeypatch.setattr(daemon, "_active_state", lambda _path: state)

    result = daemon.start_daemon(
        argparse.Namespace(
            once=False,
            audio=None,
            transcript=None,
            voice_command=None,
            command_audio="",
            background=False,
        ),
        state_path=tmp_path / "daemon.json",
        log_path=tmp_path / "daemon.log",
        launcher=lambda _env, _log: pytest.fail(
            "stopping daemon must block a replacement"
        ),
    )

    assert result == 1
    assert "VOICE_DAEMON_STOPPING pid=4242" in capsys.readouterr().out


def test_daemon_status_returns_failure_for_unreachable_instance(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon = _daemon_module()
    state = DaemonState(
        instance_id="instance-id",
        token="control-token",
        pid=4242,
        host="127.0.0.1",
        port=45454,
        status="unreachable",
    )
    monkeypatch.setattr(daemon, "_active_state", lambda _path: state)

    result = daemon.status_daemon(state_path=tmp_path / "daemon.json")

    assert result == 1
    assert "VOICE_DAEMON_UNREACHABLE pid=4242" in capsys.readouterr().out


def test_daemon_start_rejects_background_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    daemon = _daemon_module()

    result = daemon.start_daemon(
        argparse.Namespace(
            once=False,
            audio=None,
            transcript=None,
            voice_command=None,
            command_audio="",
            background=True,
        ),
        state_path=tmp_path / "daemon.json",
        log_path=tmp_path / "daemon.log",
        launcher=lambda _env, _log: pytest.fail(
            "background daemon must not launch a worker"
        ),
    )

    assert result == 2
    assert capsys.readouterr().err.startswith("VOICE_DAEMON_ERROR ")


def test_daemon_start_rejects_deterministic_fixture(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    daemon = _daemon_module()

    result = daemon.start_daemon(
        argparse.Namespace(
            once=False,
            audio=None,
            transcript="Daddy is home",
            voice_command="status",
            command_audio="",
            background=False,
        ),
        state_path=tmp_path / "daemon.json",
        log_path=tmp_path / "daemon.log",
        launcher=lambda _env, _log: pytest.fail(
            "invalid daemon options must not launch a worker"
        ),
    )

    assert result == 2
    assert capsys.readouterr().err.startswith("VOICE_DAEMON_ERROR ")


def test_daemon_worker_reports_missing_options_environment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    worker = _daemon_worker_module()
    monkeypatch.delenv(worker.OPTIONS_ENV, raising=False)
    monkeypatch.delenv(worker.READY_ENV, raising=False)

    assert worker.run_worker(argparse.Namespace()) == 1
    assert capsys.readouterr().err == (
        f"VOICE_DAEMON_ERROR '{worker.OPTIONS_ENV}'\n"
    )


def test_voice_runtime_setup_error_is_fatal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    controller = importlib.import_module("birkin.voice.controller")

    class BrokenSTT:
        def __init__(self, **_kwargs: object) -> None:
            raise OpenAIError("missing credentials")

    monkeypatch.setattr(controller, "OpenAISTT", BrokenSTT)
    args = build_parser().parse_args(["voice", "--once"])

    assert controller.run_once(args) == 1
    assert capsys.readouterr().err.startswith("VOICE_ERROR ")
