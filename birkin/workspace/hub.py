"""Thread-safe asynchronous workspace session hub."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from queue import Empty, Queue
from typing import final

from .contracts import ProtocolError, WorkspaceCommand
from .records import CommandReceipt, WorkspaceEvent, WorkspaceSnapshot
from .service import CommandHandler, WorkspaceService

EventSink = Callable[[str, dict[str, object]], WorkspaceEvent]
HandlerFactory = Callable[[str, EventSink], Mapping[str, CommandHandler]]


@final
class WorkspaceSession:
    def __init__(
        self,
        *,
        root: Path,
        session_id: str,
        handlers: Mapping[str, CommandHandler] | None,
        handler_factory: HandlerFactory | None,
    ) -> None:
        self.service = WorkspaceService(
            root=root,
            session_id=session_id,
            handlers=handlers or {},
        )
        if handler_factory is not None:
            self.service.set_handlers(
                handler_factory(session_id, self.service.emit)
            )
        self._condition = threading.Condition()
        self.service.set_event_listener(self._event_added)
        self._commands: Queue[
            tuple[WorkspaceCommand, CommandReceipt] | None
        ] = Queue()
        self._worker = threading.Thread(
            target=self._run_commands,
            name=f"birkin-workspace-{session_id}",
            daemon=True,
        )
        self._worker.start()
        self._closed = False
        self._last_error: str | None = None

    @property
    def session_id(self) -> str:
        return self.service.snapshot().session_id

    @property
    def closed(self) -> bool:
        with self._condition:
            return self._closed

    def submit(
        self,
        command: WorkspaceCommand,
        *,
        actor_id: str,
        on_accepted: Callable[[], None] | None = None,
    ) -> CommandReceipt:
        with self._condition:
            if self._closed:
                raise ProtocolError("workspace session is closed")
        receipt, execute = self.service.accept(command, actor_id=actor_id)
        if execute:
            if on_accepted is not None:
                on_accepted()
            self._commands.put((command, receipt))
        with self._condition:
            self._condition.notify_all()
        return receipt

    def snapshot(self) -> WorkspaceSnapshot:
        return self.service.snapshot()

    def events(self, *, after: int = 0) -> tuple[WorkspaceEvent, ...]:
        return self.service.events(after=after)

    def wait_events(
        self,
        *,
        after: int,
        until: str | None,
        timeout: float,
    ) -> tuple[WorkspaceEvent, ...]:
        def ready() -> bool:
            if self._closed:
                return True
            events = self.events(after=after)
            return bool(events) and (
                until is None or any(event.type == until for event in events)
            )

        with self._condition:
            _ = self._condition.wait_for(ready, timeout=timeout)
        return self.events(after=after)

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()
        while True:
            try:
                queued = self._commands.get_nowait()
            except Empty:
                break
            if queued is not None:
                _, receipt = queued
                _ = self.service.cancel(
                    receipt,
                    reason="workspace session closed before execution",
                )
        self._commands.put(None)
        self._worker.join(timeout=5)

    def _run_commands(self) -> None:
        while True:
            item = self._commands.get()
            if item is None:
                return
            command, receipt = item
            try:
                _ = self.service.execute(command, receipt)
            except Exception as exc:
                # WorkspaceService already persisted command.failed. Retain a
                # bounded diagnostic instead of swallowing the worker failure.
                self._last_error = str(exc)[:300]
            finally:
                with self._condition:
                    self._condition.notify_all()

    def _event_added(self, _event: WorkspaceEvent) -> None:
        with self._condition:
            self._condition.notify_all()


@final
class WorkspaceHub:
    def __init__(
        self,
        *,
        root: Path,
        handlers: Mapping[str, CommandHandler] | None = None,
        handler_factory: HandlerFactory | None = None,
    ) -> None:
        if handlers is None and handler_factory is None:
            raise ValueError("handlers or handler_factory is required")
        if handlers is not None and handler_factory is not None:
            raise ValueError("handlers and handler_factory are mutually exclusive")
        self._root = root
        self._handlers = dict(handlers) if handlers is not None else None
        self._handler_factory = handler_factory
        self._sessions: dict[str, WorkspaceSession] = {}
        self._lock = threading.Lock()

    def create(self, session_id: str) -> tuple[WorkspaceSession, bool]:
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                return existing, False
            session = WorkspaceSession(
                root=self._root,
                session_id=session_id,
                handlers=self._handlers,
                handler_factory=self._handler_factory,
            )
            self._sessions[session_id] = session
            return session, True

    def get(self, session_id: str) -> WorkspaceSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def summaries(self) -> list[dict[str, object]]:
        with self._lock:
            sessions = list(self._sessions.values())
        return [
            {
                "session_id": session.session_id,
                "cursor": session.snapshot().cursor,
            }
            for session in sessions
        ]

    def close(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()
