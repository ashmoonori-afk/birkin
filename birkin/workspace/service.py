"""Serial command service shared by terminal and web workspace clients."""

from __future__ import annotations

import threading
from dataclasses import replace
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast, final

from .contracts import (
    CONTROL_COMMAND_TYPES,
    REDACTION_MARKER,
    JsonValue,
    ProtocolError,
    UnsupportedCommand,
    WorkspaceCommand,
)
from .approval_projection import approval_items, approval_policy
from .journal import WorkspaceJournal
from .notifications import approval_waiting_notification
from .presets import SESSION_PRESETS, SessionPreset
from .redaction import bounded_error_text
from .records import (
    CommandReceipt,
    WorkspaceEvent,
    WorkspaceSnapshot,
)
from .snapshot import reduce_snapshot
from .working_memory import project_working_memory
from ..work_items import grouped as grouped_work_items

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
        self._receipt_lock = threading.Lock()
        self._active_receipts: dict[int, CommandReceipt] = {}
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
        with self._receipt_lock:
            receipt = self._active_receipts.get(threading.get_ident())
        if receipt is None:
            raise ProtocolError("workspace event emitted outside a command")
        event = self._append(
            event_type,
            actor_id=receipt.actor_id,
            command_id=receipt.command_id,
            payload=payload,
        )
        if event_type == "approval.requested":
            approval_id = payload.get("approval_id")
            if isinstance(approval_id, str) and approval_id:
                notification = approval_waiting_notification(approval_id)
                notification_id = notification["notification_id"]
                already_emitted = any(
                    previous.type == "notification.requested"
                    and previous.payload.get("notification_id") == notification_id
                    for previous in self._journal.events()
                )
                if not already_emitted:
                    _ = self._append(
                        "notification.requested",
                        actor_id=receipt.actor_id,
                        command_id=receipt.command_id,
                        payload=notification,
                    )
        return event

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

    def submit_control(
        self,
        command: WorkspaceCommand,
        *,
        actor_id: str,
    ) -> CommandReceipt:
        """Execute an explicit turn control outside the normal command lock."""
        if command.type not in CONTROL_COMMAND_TYPES:
            raise ProtocolError("command is not a concurrent turn control")
        receipt, execute = self.accept(command, actor_id=actor_id)
        if not execute:
            return receipt
        return self._execute(command, receipt)

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
            return self._execute(command, receipt)

    def _execute(
        self,
        command: WorkspaceCommand,
        receipt: CommandReceipt,
    ) -> CommandReceipt:
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
        thread_id = threading.get_ident()
        with self._receipt_lock:
            self._active_receipts[thread_id] = receipt
        try:
            result = handler(command.payload)
        except Exception as exc:
            failed = self._append(
                "command.failed",
                actor_id=receipt.actor_id,
                command_id=command.command_id,
                payload={"error": bounded_error_text(str(exc))},
            )
            _ = self._journal.complete(
                receipt,
                state="failed",
                result_cursor=failed.cursor,
            )
            raise
        finally:
            with self._receipt_lock:
                del self._active_receipts[thread_id]
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

    def cursor(self) -> int:
        return self._journal.cursor()

    def snapshot(self) -> WorkspaceSnapshot:
        snapshot = reduce_snapshot(
            self._journal.session_id,
            self._journal.events(),
        )
        files = next(
            panel.items for panel in snapshot.panels if panel.key == "files_evidence"
        )
        work_groups = grouped_work_items()
        from ..m365_connection import status as connection_status

        connection = connection_status()
        account = cast("dict[str, object] | None", connection.get("account"))
        connection_row = {
            "id": "connection:microsoft-365",
            "kind": "connection",
            "summary": f"Microsoft 365 · {account.get('name') if account else '연결되지 않음'}",
            "description": " · ".join(cast("list[str]", connection.get("scopes", []))),
            "status": connection["state"],
        }
        from ..daily_briefing import latest as latest_briefings

        briefing_rows = tuple({
            "id": f"briefing:{item['id']}",
            "kind": "briefing",
            "summary": "일일 브리핑",
            "description": f"기준 시각 {item['data_basis_at']}",
            "status": "확인 필요",
            "updated_at": item["data_basis_at"],
        } for item in latest_briefings(5))
        seen: set[str] = set()
        work_rows: list[dict[str, object]] = []
        for group in ("overdue", "today", "needs_confirmation", "recently_completed"):
            for item in work_groups[group]:
                item_id = str(item["id"])
                if item_id in seen:
                    continue
                seen.add(item_id)
                source = cast("dict[str, str]", item["source"])
                work_rows.append({
                    "id": item_id,
                    "kind": "work_item",
                    "summary": item["title"],
                    "description": " · ".join(filter(None, [
                        str(item.get("assignee") or "담당자 미정"),
                        str(item.get("due_date") or "기한 미정"),
                    ])),
                    "status": {
                        "overdue": "지연",
                        "today": "오늘",
                        "needs_confirmation": "확인 필요",
                        "recently_completed": "최근 완료",
                    }[group],
                    "updated_at": item["updated_at"],
                    "session_id": item.get("session_id") or "",
                    "target": next(iter(source.values()), ""),
                })
        panels = tuple(
            replace(panel, items=approval_items(panel.items))
            if panel.key == "approvals"
            else replace(panel, items=briefing_rows + tuple(work_rows) + panel.items)
            if panel.key == "tasks_runs"
            else replace(panel, items=(connection_row,) + panel.items)
            if panel.key == "files_evidence"
            else panel
            for panel in snapshot.panels
        )
        return replace(
            snapshot,
            panels=panels,
            working_memory=project_working_memory(snapshot.session_id, files),
            approval_policy=approval_policy(),
        )
