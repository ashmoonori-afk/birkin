"""Process-boundary regressions for gateway hard restart."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from typing_extensions import override

from birkin import config
from birkin.approval_execution_codec import JSONValue
from birkin.gateway.channels.base import ProgressCallback
from birkin.gateway.channels.telegram import TelegramChannel
from birkin.gateway.core import Gateway


def _gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Gateway:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    cfg = {
        **config.DEFAULT_CONFIG,
        "provider": "claude-cli",
        "gateway_persistent": True,
    }
    _ = config.save_config(cfg)
    return Gateway(config.load_config())


def test_hard_restart_spawns_one_replacement_and_exits_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _gateway(tmp_path, monkeypatch)
    spawned: list[tuple[list[str], dict[str, int | bool]]] = []
    exits: list[int] = []
    execs: list[list[str]] = []

    def fake_popen(argv: list[str], **kwargs: int | bool) -> None:
        spawned.append((argv, kwargs))

    def fake_execv(_path: str, argv: list[str]) -> None:
        execs.append(argv)

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(
        subprocess,
        "CREATE_BREAKAWAY_FROM_JOB",
        0x1000000,
        raising=False,
    )
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(os, "_exit", exits.append)
    monkeypatch.setattr(os, "execv", fake_execv)

    gateway.do_hard_restart()

    assert spawned == [
        (
            [sys.executable, "-m", "birkin", "gateway"],
            {"close_fds": True, "creationflags": 0x1000200},
        )
    ]
    assert exits == [0]
    assert execs == []


def test_telegram_hard_restart_does_not_start_second_get_updates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    restarts: list[bool] = []
    get_updates_threads: list[int] = []
    restart_called = threading.Event()
    main_thread = threading.get_ident()
    channel = TelegramChannel("token", allowed_chat_ids=["42"], stream=False)
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))

    def record_call(
        method: str,
        _params: dict[str, JSONValue],
        timeout: int = 60,
    ) -> dict[str, JSONValue]:
        _ = (_params, timeout)
        calls.append(method)
        if method == "getUpdates":
            get_updates_threads.append(threading.get_ident())
            if len(get_updates_threads) == 1:
                return {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 1,
                            "message": {
                                "chat": {"id": "42"},
                                "text": "/hard-restart",
                            },
                        }
                    ],
                }
            if threading.get_ident() == main_thread:
                assert restart_called.wait(5)
                raise SystemExit
        return {"ok": True}

    def send_reply(_chat_id: str, _text: str) -> bool:
        return True

    monkeypatch.setattr(channel, "_call", record_call)
    monkeypatch.setattr(channel, "_send_reply", send_reply)

    class _RestartingGateway(Gateway):
        @property
        @override
        def pending_hard_restart(self) -> bool:
            return True

        @override
        def do_hard_restart(self) -> None:
            restarts.append(True)
            restart_called.set()

        @override
        def interrupt(self, channel: str, chat_id: str) -> bool:
            _ = (channel, chat_id)
            return False

        @override
        def take_restart_greeting(self, channel: str) -> str | None:
            _ = channel
            return None

        @override
        def command_menu(self) -> list[dict[str, str]]:
            return []

        @override
        def _command_trusted(self, channel: str) -> bool:
            _ = channel
            return True

        @override
        def handle(
            self,
            channel: str,
            chat_id: str,
            text: str,
            on_text: Callable[[str], None] | None = None,
            workflow_id: str | None = None,
            on_progress: ProgressCallback = None,
            sender_id: str | None = None,
        ) -> str:
            _ = (
                channel,
                chat_id,
                text,
                on_text,
                workflow_id,
                on_progress,
                sender_id,
            )
            return "restarting"

    gateway = _RestartingGateway.__new__(_RestartingGateway)
    with pytest.raises(SystemExit):
        channel.start(gateway)

    assert get_updates_threads == [main_thread, main_thread]
    assert restarts == [True]
