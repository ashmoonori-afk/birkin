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
        self._session_names: dict[str, str] = {}
        self._selected_session_id: str | None = None
        self._event_listeners: list[Callable[[WorkspaceEvent], None]] = []
        self._lock = threading.RLock()

    def create(self, session_id: str) -> tuple[WorkspaceSession, bool]:
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                return existing, False
            handlers = dict(self._handlers or {})
            if self._handler_factory is not None:
                factory = self._handler_factory

                def combined_factory(
                    created_session_id: str,
                    emit: EventSink,
                ) -> Mapping[str, CommandHandler]:
                    return {
                        **factory(created_session_id, emit),
                        **self._lifecycle_handlers(emit),
                    }

                handler_factory: HandlerFactory | None = combined_factory
                configured_handlers: Mapping[str, CommandHandler] | None = None
            else:
                def static_factory(
                    _created_session_id: str,
                    emit: EventSink,
                ) -> Mapping[str, CommandHandler]:
                    return {**handlers, **self._lifecycle_handlers(emit)}

                handler_factory = static_factory
                configured_handlers = None
            session = WorkspaceSession(
                root=self._root,
                session_id=session_id,
                handlers=configured_handlers,
                handler_factory=handler_factory,
            )
            for listener in self._event_listeners:
                _ = session.service.add_event_listener(listener)
            self._sessions[session_id] = session
            self._session_names[session_id] = session_id
            if self._selected_session_id is None:
                self._selected_session_id = session_id
            return session, True

    @property
    def supported_commands(self) -> frozenset[str]:
        with self._lock:
            session = self._selected_session()
            return session.service.supported_commands

    def get(self, session_id: str) -> WorkspaceSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def snapshot(self) -> WorkspaceSnapshot:
        with self._lock:
            return self._selected_session().snapshot()

    def events(self, *, after: int = 0) -> tuple[WorkspaceEvent, ...]:
        with self._lock:
            return self._selected_session().events(after=after)

    def add_event_listener(
        self,
        listener: Callable[[WorkspaceEvent], None],
    ) -> Callable[[], None]:
        with self._lock:
            self._event_listeners.append(listener)
            sessions = list(self._sessions.values())
        unsubscribers = [
            session.service.add_event_listener(listener) for session in sessions
        ]

        def unsubscribe() -> None:
            for remove in unsubscribers:
                remove()
            with self._lock:
                if listener in self._event_listeners:
                    self._event_listeners.remove(listener)

        return unsubscribe

    def select(
        self,
        command: WorkspaceCommand,
        *,
        actor_id: str,
    ) -> CommandReceipt:
        if command.type != "session.select":
            raise ProtocolError("session.select command is required")
        with self._lock:
            session = self._selected_session()
        return session.service.submit(command, actor_id=actor_id)

    def rename(
        self,
        command: WorkspaceCommand,
        *,
        actor_id: str,
    ) -> CommandReceipt:
        if command.type != "session.rename":
            raise ProtocolError("session.rename command is required")
        with self._lock:
            session = self._selected_session()
        return session.service.submit(command, actor_id=actor_id)

    def compact(
        self,
        command: WorkspaceCommand,
        *,
        actor_id: str,
    ) -> CommandReceipt:
        if command.type != "session.compact":
            raise ProtocolError("session.compact command is required")
        with self._lock:
            session = self._selected_session()
        return session.service.submit(command, actor_id=actor_id)

    def _selected_session(self) -> WorkspaceSession:
        session_id = self._selected_session_id
        if session_id is None or session_id not in self._sessions:
            raise ProtocolError("no workspace session is selected")
        return self._sessions[session_id]

    def _lifecycle_handlers(
        self,
        emit: EventSink,
    ) -> Mapping[str, CommandHandler]:
        def select(payload: dict[str, object]) -> dict[str, object]:
            session_id = payload.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise ProtocolError("session_id is required")
            with self._lock:
                if session_id not in self._sessions:
                    raise ProtocolError("workspace session was not found")
                _ = emit("session.selected", {"session_id": session_id})
                self._selected_session_id = session_id
            return {"session_id": session_id}

        def rename(payload: dict[str, object]) -> dict[str, object]:
            session_id = payload.get("session_id")
            name = payload.get("name")
            if not isinstance(session_id, str) or not session_id:
                raise ProtocolError("session_id is required")
            if not isinstance(name, str) or not name.strip():
                raise ProtocolError("session name is required")
            cleaned = name.strip()
            with self._lock:
                if session_id not in self._sessions:
                    raise ProtocolError("workspace session was not found")
                self._session_names[session_id] = cleaned
                _ = emit(
                    "session.renamed",
                    {"session_id": session_id, "name": cleaned},
                )
            return {"session_id": session_id, "name": cleaned}

        return {
            "session.select": select,
            "session.rename": rename,
        }

    def summaries(self) -> list[dict[str, object]]:
        with self._lock:
            sessions = list(self._sessions.values())
        return [
            {
                "session_id": session.session_id,
                "name": self._session_names[session.session_id],
                "cursor": session.snapshot().cursor,
            }
            for session in sessions
        ]

    def close(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._session_names.clear()
            self._selected_session_id = None
        for session in sessions:
            session.close()
