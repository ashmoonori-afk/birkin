"""Serial command service shared by terminal and web workspace clients."""

from __future__ import annotations

import threading
from dataclasses import replace
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import final

from .contracts import (
    REDACTION_MARKER,
    JsonValue,
    ProtocolError,
    UnsupportedCommand,
    WorkspaceCommand,
)
from .approval_projection import approval_items, approval_policy
from .journal import WorkspaceJournal
from .presets import SESSION_PRESETS, SessionPreset
from .records import (
    CommandReceipt,
    WorkspaceEvent,
    WorkspaceSnapshot,
)
from .snapshot import reduce_snapshot
from .working_memory import project_working_memory

CommandHandler = Callable[[dict[str, JsonValue]], dict[str, JsonValue]]
EventListener = Callable[[WorkspaceEvent], None]


@final
class WorkspaceService:
    """Execute one session's commands in accepted event order."""

    @property
    def supported_commands(self) -> frozenset[str]:
        return frozenset(self._handlers)

    @property
    def session_presets(self) -> tuple[SessionPreset, ...]:
        return SESSION_PRESETS

    def __init__(
        self,
        *,
        root: Path,
        session_id: str,
        handlers: Mapping[str, CommandHandler],
    ) -> None:
        self._journal = WorkspaceJournal(root, session_id)
        self._handlers = dict(handlers)
        self._lock = threading.RLock()
        self._active_receipt: CommandReceipt | None = None
        self._event_listeners: list[EventListener] = []

    def set_handlers(self, handlers: Mapping[str, CommandHandler]) -> None:
        with self._lock:
            if self._handlers:
                raise ProtocolError("workspace handlers are already configured")
            self._handlers = dict(handlers)

    def set_event_listener(self, listener: EventListener) -> None:
        with self._lock:
            self._event_listeners = [listener]

    def add_event_listener(
        self,
        listener: EventListener,
    ) -> Callable[[], None]:
        with self._lock:
            self._event_listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._event_listeners:
                    self._event_listeners.remove(listener)

        return unsubscribe

    def _notify(self, event: WorkspaceEvent) -> None:
        for listener in tuple(self._event_listeners):
            listener(event)

    def _append(
        self,
        event_type: str,
        *,
        actor_id: str,
        command_id: str,
        payload: dict[str, object],
    ) -> WorkspaceEvent:
        event = self._journal.append(
            event_type,
            actor_id=actor_id,
            command_id=command_id,
            payload=payload,
        )
        self._notify(event)
        return event

    def emit(
        self,
        event_type: str,
        payload: dict[str, object],
    ) -> WorkspaceEvent:
        with self._lock:
            receipt = self._active_receipt
            if receipt is None:
                raise ProtocolError("workspace event emitted outside a command")
            return self._append(
                event_type,
                actor_id=receipt.actor_id,
                command_id=receipt.command_id,
                payload=payload,
            )

    def submit(
        self,
        command: WorkspaceCommand,
        *,
        actor_id: str,
    ) -> CommandReceipt:
        receipt, execute = self.accept(command, actor_id=actor_id)
        if not execute:
            return receipt
        return self.execute(command, receipt)

    def accept(
        self,
        command: WorkspaceCommand,
        *,
        actor_id: str,
    ) -> tuple[CommandReceipt, bool]:
        receipt, execute = self._journal.accept(command, actor_id=actor_id)
        if execute:
            accepted = self._journal.events(
                after=receipt.accepted_cursor - 1
            )
            if accepted:
                self._notify(accepted[0])
        return receipt, execute

    def execute(
        self,
        command: WorkspaceCommand,
        receipt: CommandReceipt,
    ) -> CommandReceipt:
        with self._lock:
            handler = self._handlers.get(command.type)
            if handler is None:
                failed = self._append(
                    "command.failed",
                    actor_id=receipt.actor_id,
                    command_id=command.command_id,
                    payload={"error": "unsupported command handler"},
                )
                _ = self._journal.complete(
                    receipt,
                    state="failed",
                    result_cursor=failed.cursor,
                )
                raise UnsupportedCommand(f"no handler for {command.type}")
            _ = self._append(
                "command.started",
                actor_id=receipt.actor_id,
                command_id=command.command_id,
                payload={"command_type": command.type},
            )
            self._active_receipt = receipt
            try:
                result = handler(command.payload)
            except Exception as exc:
                failed = self._append(
                    "command.failed",
                    actor_id=receipt.actor_id,
                    command_id=command.command_id,
                    payload={"error": str(exc)[:300]},
                )
                _ = self._journal.complete(
                    receipt,
                    state="failed",
                    result_cursor=failed.cursor,
                )
                raise
            finally:
                self._active_receipt = None
            durable_result = result
            if command.type == "terminal.create" and "lease" in result:
                durable_result = {**result, "lease": REDACTION_MARKER}
            completed = self._append(
                "command.completed",
                actor_id=receipt.actor_id,
                command_id=command.command_id,
                payload={"result": durable_result},
            )
            completed_receipt = self._journal.complete(
                receipt,
                state="completed",
                result_cursor=completed.cursor,
            )
            return replace(completed_receipt, transient_result=result)

    def cancel(
        self,
        receipt: CommandReceipt,
        *,
        reason: str,
    ) -> CommandReceipt:
        failed = self._journal.append(
            "command.failed",
            actor_id=receipt.actor_id,
            command_id=receipt.command_id,
            payload={"error": reason},
        )
        return self._journal.complete(
            receipt,
            state="failed",
            result_cursor=failed.cursor,
        )

    def events(self, *, after: int = 0) -> tuple[WorkspaceEvent, ...]:
        return self._journal.events(after=after)

    def snapshot(self) -> WorkspaceSnapshot:
        snapshot = reduce_snapshot(
            self._journal.session_id,
            self._journal.events(),
        )
        files = next(
            panel.items for panel in snapshot.panels if panel.key == "files_evidence"
        )
        panels = tuple(
            replace(panel, items=approval_items(panel.items))
            if panel.key == "approvals"
            else panel
            for panel in snapshot.panels
        )
        return replace(
            snapshot,
            panels=panels,
            working_memory=project_working_memory(snapshot.session_id, files),
            approval_policy=approval_policy(),
        )
