"""Detached voice daemon lifecycle commands."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from .daemon_readiness import await_worker
from .daemon_state import (
    DaemonState,
    create_control_listener,
    request,
)
from .daemon_storage import (
    daemon_paths,
    load_state,
    remove_state,
)
from .daemon_worker import (
    OPTIONS_ENV,
    READY_ENV,
    READY_TIMEOUT_SECONDS,
    VOICE_ARGUMENTS,
)


class ChildProcess(Protocol):
    pid: int

    def terminate(self) -> None: ...


Launcher = Callable[[Mapping[str, str], Path], ChildProcess]


def start_daemon(
    args: argparse.Namespace,
    *,
    state_path: Path | None = None,
    log_path: Path | None = None,
    launcher: Launcher | None = None,
) -> int:
    if args.once or any(
        getattr(args, name, None)
        for name in (
            "audio",
            "transcript",
            "voice_command",
            "command_audio",
            "background",
        )
    ):
        print(
            "VOICE_DAEMON_ERROR start accepts live microphone input only",
            file=sys.stderr,
        )
        return 2
    default_state, default_log = daemon_paths()
    state_path = state_path or default_state
    log_path = log_path or default_log
    existing = _active_state(state_path)
    if existing is not None:
        print(f"VOICE_DAEMON_{existing.status.upper()} pid={existing.pid}")
        return 0 if existing.status == "running" else 1

    listener = create_control_listener()
    ready_token = secrets.token_urlsafe(32)
    ready_port = listener.getsockname()[1]
    env = dict(os.environ)
    env[READY_ENV] = json.dumps(
        {"port": ready_port, "token": ready_token}
    )
    env[OPTIONS_ENV] = json.dumps(
        {
            name: getattr(args, name, None)
            for name in VOICE_ARGUMENTS
        }
    )
    process: ChildProcess | None = None
    try:
        process = (launcher or _launch)(env, log_path)
        state = await_worker(
            listener,
            ready_token,
            READY_TIMEOUT_SECONDS,
        )
    except (
        OSError,
        TimeoutError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        if process is not None:
            process.terminate()
        print(f"VOICE_DAEMON_ERROR {exc}", file=sys.stderr)
        return 1
    finally:
        listener.close()
    print(f"VOICE_DAEMON_STARTED pid={state.pid}")
    return 0


def status_daemon(*, state_path: Path | None = None) -> int:
    state_path = state_path or daemon_paths()[0]
    state = _active_state(state_path)
    if state is None:
        print("VOICE_DAEMON_INACTIVE")
        return 1
    print(f"VOICE_DAEMON_{state.status.upper()} pid={state.pid}")
    return 0 if state.status == "running" else 1


def stop_daemon(*, state_path: Path | None = None) -> int:
    state_path = state_path or daemon_paths()[0]
    try:
        state = load_state(state_path)
        status = request(state, "STOP")
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        print("VOICE_DAEMON_INACTIVE")
        return 1
    print(f"VOICE_DAEMON_{status.upper()} pid={state.pid}")
    return 0 if status == "stopped" else 1


def _active_state(path: Path) -> DaemonState | None:
    try:
        state = load_state(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        path.unlink(missing_ok=True)
        return None
    try:
        status = request(state, "STATUS")
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        if _pid_alive(state.pid):
            return replace(state, status="unreachable")
        remove_state(path, state.instance_id)
        return None
    if status == "running":
        return state
    if status == "stopping":
        return replace(state, status="stopping")
    remove_state(path, state.instance_id)
    return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _launch(
    env: Mapping[str, str],
    log_path: Path,
) -> subprocess.Popen[bytes]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("ab")
    command = [sys.executable, "-m", "birkin", "voice", "--daemon-worker"]
    try:
        if os.name == "nt":
            return subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=dict(env),
                close_fds=True,
                creationflags=(
                    getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                    | getattr(
                        subprocess,
                        "CREATE_NEW_PROCESS_GROUP",
                        0x00000200,
                    )
                    | getattr(
                        subprocess,
                        "CREATE_NO_WINDOW",
                        0x08000000,
                    )
                ),
            )
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=dict(env),
            close_fds=True,
            start_new_session=True,
        )
    finally:
        log.close()
