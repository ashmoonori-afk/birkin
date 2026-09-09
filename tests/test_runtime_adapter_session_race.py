"""Exactly one runtime session is built, whoever asks first.

Two threads observing ``_session is None`` (a first ``chat.send`` racing
``chat.interrupt``) used to build two subprocess-backed sessions; the one
that received the interrupt was then discarded.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from birkin.workspace import runtime_adapter as module
from birkin.workspace.records import WorkspaceEvent


class _FakeSession:
    def __init__(self, who: str) -> None:
        self.who = who
        self.abort = threading.Event()


def _emit(kind: str, payload: dict[str, object]) -> WorkspaceEvent:
    return WorkspaceEvent(
        protocol_version=1, session_id="race", cursor=1, event_id="event-1",
        type=kind, timestamp="2026-09-09T00:00:00Z", actor_id="test",
        command_id="cmd-1", payload=payload,
    )


def test_concurrent_first_access_builds_one_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    worker_entered = threading.Event()
    release_worker = threading.Event()
    built: list[_FakeSession] = []

    def build(*_args: object, **_kwargs: object) -> _FakeSession:
        session = _FakeSession(threading.current_thread().name)
        built.append(session)
        if session.who == "worker":
            worker_entered.set()
            assert release_worker.wait(5)
        return session

    monkeypatch.setattr(module, "build_session", build)
    monkeypatch.setattr(module.config, "load_config", lambda: {})
    adapter = module.RuntimeWorkspaceAdapter(
        "race", _emit, workspace_root=tmp_path / "workspace"
    )

    worker = threading.Thread(target=adapter.runtime_session, name="worker")
    interrupt = threading.Thread(target=adapter.interrupt_now, name="interrupt")
    worker.start()
    assert worker_entered.wait(5)
    interrupt.start()
    release_worker.set()
    worker.join(5)
    interrupt.join(5)

    assert [s.who for s in built] == ["worker"]
    assert adapter.runtime_session() is built[0]
    assert built[0].abort.is_set()
