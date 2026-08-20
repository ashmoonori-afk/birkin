"""Adapt a real runtime.Session to workspace command/event semantics."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from typing import cast, final

from .. import approvals, config, transcripts, uistate, workbench
from ..computer_use.events import ComputerEvent
from ..computer_use.reducer import ComputerState, reduce_event
from ..runtime import Session, build_session
from .records import PanelSummary, WorkspaceEvent, WorkspaceSnapshot
from .service import CommandHandler

EventSink = Callable[[str, dict[str, object]], WorkspaceEvent]

_EXTERNAL_PANEL_SOURCES = {
    "tasks_runs": "agents",
    "approvals": "approvals",
    "files_evidence": "checkpoints",
    "sessions_history": "sessions",
    "activity_logs": "activity",
    "cron": "cron",
    "memory_skills": "zones",
    "checkpoints_restore": "checkpoints",
    "settings_status": "header",
}


def _external_item(
    panel_key: str,
    raw: object,
    index: int,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        return {
            "id": f"{panel_key}:{index}",
            "summary": str(raw),
            "ui_state": "unknown",
            "kind": panel_key,
        }
    item = cast(dict[str, object], raw)
    identifier = (
        item.get("id") or item.get("hash") or item.get("name") or f"{panel_key}:{index}"
    )
    summary = (
        item.get("summary")
        or item.get("title")
        or item.get("name")
        or item.get("path")
        or identifier
    )
    status = str(item.get("ui_state") or item.get("status") or "unknown")
    state = {
        "active": "running",
        "running": "running",
        "pending": "pending",
        "failed": "failed",
        "complete": "succeeded",
        "completed": "succeeded",
        "succeeded": "succeeded",
    }.get(status.lower(), status)
    kinds = {
        "approvals": "approval",
        "checkpoints_restore": "checkpoint",
        "files_evidence": "evidence",
        "cron": "cron",
    }
    return {
        **item,
        "id": str(identifier),
        "summary": str(summary),
        "ui_state": state,
        "kind": kinds.get(panel_key, panel_key),
    }


@final
class RuntimeWorkspaceAdapter:
    def __init__(
        self,
        session_id: str,
        emit: EventSink,
    ) -> None:
        self._session_id = session_id
        self._emit = emit
        self._session: Session | None = None
        self._computer_state = ComputerState()
        self._run_id = (
            f"workspace-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{os.getpid()}"
        )

    def handlers(self) -> Mapping[str, CommandHandler]:
        return {
            "chat.send": self._chat_send,
            "chat.interrupt": self._chat_interrupt,
            "chat.resume": self._chat_resume,
            "approval.answer": self._approval_answer,
            "question.answer": self._question_answer,
            "session.compact": self._session_compact,
        }

    def close(self) -> None:
        if self._session is not None:
            self._session.abort.set()
            self._session.close()
            self._session = None

    def runtime_session(self) -> Session:
        return self._get_session()

    def enrich_snapshot(
        self,
        snapshot: WorkspaceSnapshot,
    ) -> WorkspaceSnapshot:
        raw_value = cast(object, workbench.snapshot(self._get_session()))
        if not isinstance(raw_value, dict):
            return snapshot
        raw = cast(dict[str, object], raw_value)
        panels: list[PanelSummary] = []
        for panel in snapshot.panels:
            source_key = _EXTERNAL_PANEL_SOURCES.get(panel.key)
            if source_key is None:
                panels.append(panel)
                continue
            source = raw.get(source_key, [])
            values = (
                cast(list[object], source) if isinstance(source, list) else [source]
            )
            merged = {
                str(item.get("id")): item
                for item in (
                    _external_item(panel.key, value, index)
                    for index, value in enumerate(values)
                )
                if item.get("summary")
            }
            for item in panel.items:
                merged[str(item.get("id"))] = item
            panels.append(replace(panel, items=tuple(merged.values())))
        return replace(snapshot, panels=tuple(panels))

    def interrupt_now(self) -> None:
        self._get_session().abort.set()

    def compact(self) -> bool:
        """Compact through the runtime's canonical agent entry point."""
        return self._get_session().agent.compact_now("manual")

    def _get_session(self) -> Session:
        if self._session is None:
            cfg = config.load_config()
            cfg["session_id"] = self._session_id
            self._session = build_session(cfg, on_event=self._runtime_event)
        return self._session

    def _runtime_event(
        self,
        event: str,
        payload: dict[str, object],
    ) -> None:
        if event == "computer_use":
            self._computer_event(payload)
            return
        is_error = bool(payload.get("is_error", False))
        event_type = {
            "tool_start": "tool.started",
            "tool_end": "tool.completed",
            "subagent.start": "task.updated",
            "subagent.done": "task.updated",
            "compact": "progress.updated",
            "steer": "progress.updated",
        }.get(event, "progress.updated")
        if event == "tool_end" and is_error:
            event_type = "tool.failed"
        safe: dict[str, object] = {
            "runtime_event": event,
            "summary": str(payload.get("name") or payload.get("summary") or "")[:300],
            "state": uistate.from_runtime(event, is_error=is_error).state,
        }
        _ = self._emit(event_type, safe)

    def _computer_event(self, raw: dict[str, object]) -> None:
        version = raw.get("version")
        sequence = raw.get("sequence")
        session_id = raw.get("session_id")
        kind = raw.get("kind")
        payload = raw.get("payload")
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or not isinstance(session_id, str)
            or not isinstance(kind, str)
            or not isinstance(payload, dict)
        ):
            return
        event = ComputerEvent(
            version=version,
            sequence=sequence,
            session_id=session_id,
            kind=kind,
            payload=cast(dict[str, object], payload),
        )
        try:
            self._computer_state = reduce_event(self._computer_state, event)
        except ValueError:
            return
        effect = event.payload.get("effect")
        refusal = event.payload.get("refusal_code")
        approval_id = event.payload.get("approval_id")
        started = event.kind.endswith(".started")
        status = str(effect or refusal or event.kind.rsplit(".", 1)[-1])
        ui_state = (
            "running"
            if started
            else "action_needed"
            if isinstance(approval_id, str)
            else "succeeded"
            if event.payload.get("ok") is True
            else "failed"
        )
        safe: dict[str, object] = {
            "runtime_event": "computer_use",
            "summary": f"{event.kind} · {status}",
            "status": status,
            "ui_state": ui_state,
            "kind": "computer_use",
            "computer_event": event.to_dict(),
            "computer_sequence": event.sequence,
        }
        for key in (
            "approval_id",
            "review_id",
            "receipt_ref",
            "snapshot_ref",
            "effect",
            "refusal_code",
        ):
            value = event.payload.get(key)
            if isinstance(value, str):
                safe[key] = value
        focus = event.payload.get("focus")
        if isinstance(focus, dict) and isinstance(
            focus.get("preserved"),
            bool,
        ):
            safe["focus_preserved"] = focus["preserved"]
        _ = self._emit("computer.updated", safe)

    def _chat_send(self, payload: dict[str, object]) -> dict[str, object]:
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("chat text must be non-empty")
        _ = self._emit("message.user", {"text": text})
        pieces: list[str] = []

        def on_text(piece: str) -> None:
            pieces.append(piece)
            _ = self._emit("message.assistant.delta", {"text": piece})

        session = self._get_session()
        reply = session.ask(text, on_text=on_text)
        final = reply or "".join(pieces)
        _ = self._emit("message.assistant.completed", {"text": final})
        _ = transcripts.append_turn(
            "workspace",
            self._run_id,
            text,
            final,
            cfg=session.cfg,
        )
        return {"reply": final}

    def _session_compact(
        self,
        _payload: dict[str, object],
    ) -> dict[str, object]:
        compacted = self.compact()
        _ = self._emit(
            "session.compacted",
            {"session_id": self._session_id, "compacted": compacted},
        )
        return {"compacted": compacted}

    def _chat_interrupt(self, _payload: dict[str, object]) -> dict[str, object]:
        session = self._get_session()
        session.abort.set()
        _ = self._emit("turn.interrupted", {})
        return {"interrupted": True}

    def _chat_resume(self, _payload: dict[str, object]) -> dict[str, object]:
        session = self._get_session()
        session.abort.clear()
        _ = self._emit("turn.resumed", {})
        return {"resumed": True}

    def _approval_answer(self, payload: dict[str, object]) -> dict[str, object]:
        approval_id = payload.get("approval_id")
        decision = payload.get("decision")
        if not isinstance(approval_id, str):
            raise TypeError("approval_id is required")
        if decision == "approve":
            result = approvals.approve(approval_id)
        elif decision == "reject":
            result = approvals.reject(
                approval_id,
                reason=str(payload.get("reason") or ""),
            )
        else:
            raise ValueError("decision must be approve or reject")
        event_payload: dict[str, object] = {
            "approval_id": approval_id,
            "decision": str(decision),
        }
        if decision == "approve":
            event_payload["receipt"] = str(result)
        _ = self._emit("approval.answered", event_payload)
        return {"result": str(result)}

    def _question_answer(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        question_id = payload.get("question_id")
        answer = payload.get("answer")
        if not isinstance(question_id, str) or not question_id:
            raise ValueError("question_id is required")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("answer is required")
        cleaned = answer.strip()
        _ = self._emit(
            "question.answered",
            {
                "question_id": question_id,
                "answer": cleaned,
                "ui_state": "succeeded",
            },
        )
        return self._chat_send({"text": cleaned})
