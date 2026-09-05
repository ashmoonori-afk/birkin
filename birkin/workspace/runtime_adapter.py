"""Adapt a real runtime.Session to workspace command/event semantics."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import cast, final

from .. import approvals, config, risk, store, transcripts, uistate, workbench
from ..browser_aside_control import BrowserControlAuthority
from ..browser_aside_service import BrowserAsideService
from ..computer_use.events import ComputerEvent
from ..computer_use.reducer import ComputerState, reduce_event
from ..computer_use.runtime import default_backend
from ..native.jailed_import import JailedImportAuthority
from ..llm import LLMError, LLMStatus
from ..office.adapters.catalog import supported_formats
from ..office.coordinator_data import canonical_office_home
from ..office.presentation import format_preview_replacements
from ..office.preview_semantics import PreviewSummary
from ..office.service import DocumentService
from ..runtime import Session, build_session

from . import approval_authority
from .decision_text import llm_status_summary, provider_failure
from .approval_receipts import (
    OfficeReceiptProjection,
    approval_turn_context,
    job_id_from_receipt_ref,
)
from .owned_terminal import TerminalAuthority
from .records import PanelSummary, WorkspaceEvent, WorkspaceSnapshot
from .working_memory import memory_write_handler
from .service import CommandHandler

EventSink = Callable[[str, dict[str, object]], WorkspaceEvent]

_REGISTERED_IMPORT_SUFFIXES = {
    f".{format_name}" for format_name in supported_formats()
} | {".txt"}

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
        *,
        workspace_root: Path | None = None,
    ) -> None:
        self._session_id = session_id
        self._emit = emit
        self._workspace_root = (workspace_root or Path.cwd()).expanduser().resolve()
        self._session: Session | None = None
        self._computer_state = ComputerState()
        self._terminal = TerminalAuthority(
            session_id=session_id,
            workspace_root=self._workspace_root,
            emit=emit,
            config_loader=config.load_config,
        )
        self._jailed_import = JailedImportAuthority(
            self._workspace_root / "imports", session_id=session_id
        )
        from ..native.product_surfaces import (
            BrowserSurfaceAuthority,
            ComputerUseSurfaceAuthority,
            NativeProductSurfaceAuthority,
            OfficeSurfaceAuthority,
        )

        self.surface_authority = NativeProductSurfaceAuthority(
            browser=BrowserSurfaceAuthority(
                BrowserAsideService(session_id), BrowserControlAuthority(time.monotonic)
            ),
            computer_use=ComputerUseSurfaceAuthority(probe=default_backend().probe()),
            office=OfficeSurfaceAuthority(DocumentService(canonical_office_home())),
        )
        self._failed_intent_payload: dict[str, object] | None = None
        self._pending_approval_context: str | None = None
        self._run_id = (
            f"workspace-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{os.getpid()}"
        )

    def handlers(self) -> Mapping[str, CommandHandler]:
        return {
            "chat.send": self._chat_send,
            "chat.steer": self._chat_steer,
            "chat.retry": self._chat_retry,
            "chat.interrupt": self._chat_interrupt,
            "chat.resume": self._chat_resume,
            "approval.answer": self._approval_answer,
            "question.answer": self._question_answer,
            "session.compact": self._session_compact,
            "memory.write": memory_write_handler(self._session_id, self._emit),
            **self._terminal.handlers(),
            "file.import": self._file_import,
            "office.job_request": self._office_job_request,
            "office.rollback_request": self._office_rollback_request,
            **self.surface_authority.handlers(self._emit),
            "office.create": self._office_create_request,
        }

    def revoke_terminal_leases(self) -> None:
        self._terminal.revoke_leases()

    def close(self) -> None:
        """Release everything this session owns, whatever fails on the way.

        The private browser is a real child process, so leaving it running
        when the bridge stops would strand it with no owner.
        """
        try:
            self._terminal.close_all()
        finally:
            try:
                _ = self.surface_authority.browser.close()
            finally:
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
            self._session = build_session(
                cfg,
                on_event=self.runtime_event,
                on_status=self.runtime_status,
            )
        return self._session

    def runtime_status(self, status: LLMStatus) -> None:
        payload: dict[str, object] = {
            "summary": llm_status_summary(status),
            "status": status.kind,
            "ui_state": (
                "succeeded"
                if status.kind == "recovered"
                else "running"
            ),
            "provider": status.provider,
            "model": status.model,
            "reason": status.reason,
        }
        optional = {
            "retry_in_seconds": status.retry_in_seconds,
            "attempt": status.attempt,
            "max_attempts": status.max_attempts,
            "provider_status": status.http_status,
            "fallback_provider": status.fallback_provider,
            "fallback_model": status.fallback_model,
        }
        payload.update({
            key: value
            for key, value in optional.items()
            if value is not None
        })
        _ = self._emit("progress.updated", payload)

    def runtime_event(
        self,
        event: str,
        payload: dict[str, object],
    ) -> None:
        if event == "computer_use":
            self._computer_event(payload)
            return
        if event == "office_progress":
            _ = self._emit(
                "progress.updated",
                {
                    key: payload[key]
                    for key in (
                        "progress_id",
                        "runtime_event",
                        "office_phase",
                        "job_id",
                        "summary",
                        "status",
                        "ui_state",
                    )
                    if key in payload
                },
            )
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
        summary = {
            "tool_start": "도구 실행을 시작했습니다.",
            "tool_end": (
                "도구 실행에 실패했습니다."
                if is_error
                else "도구 실행을 완료했습니다."
            ),
            "subagent.start": "백그라운드 작업을 시작했습니다.",
            "subagent.done": "백그라운드 작업을 완료했습니다.",
            "compact": "대화 컨텍스트를 정리했습니다.",
            "steer": "실행 방향을 업데이트했습니다.",
        }.get(event, "진행 상태가 업데이트되었습니다.")
        safe: dict[str, object] = {
            "progress_id": (
                f"runtime:{'tool' if event.startswith('tool_') else event}:"
                f"{str(payload.get('name') or payload.get('summary') or 'operation')[:80]}"
            ),
            "runtime_event": event,
            "summary": summary,
            "state": uistate.from_runtime(event, is_error=is_error).state,
        }
        safe["status"] = safe["state"]
        runtime_name = payload.get("name") or payload.get("summary")
        if runtime_name:
            safe["runtime_name"] = str(runtime_name)[:300]
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
        summary = (
            "컴퓨터 작업을 시작했습니다."
            if started
            else "컴퓨터 작업에 승인이 필요합니다."
            if isinstance(approval_id, str)
            else "컴퓨터 작업을 완료했습니다."
            if event.payload.get("ok") is True
            else (
                "컴퓨터 작업을 수행하지 못했습니다. "
                "세부 정보를 확인한 뒤 다시 시도하세요."
            )
        )
        safe: dict[str, object] = {
            "runtime_event": "computer_use",
            "summary": summary,
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
        raw_focus = event.payload.get("focus")
        if isinstance(raw_focus, dict):
            focus = cast(dict[str, object], raw_focus)
            if isinstance(focus.get("preserved"), bool):
                safe["focus_preserved"] = focus["preserved"]
        _ = self._emit("computer.updated", safe)

    def _chat_send(self, payload: dict[str, object]) -> dict[str, object]:
        if set(payload) - {"text", "attachments"}:
            raise ValueError("chat.send accepts only text and attachments")
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("chat text must be non-empty")
        raw_attachments: object = payload.get("attachments", [])
        if not isinstance(raw_attachments, list):
            raise ValueError("chat attachments must be an array of at most 16 imports")
        attachment_values = cast(list[object], raw_attachments)
        if len(attachment_values) > 16:
            raise ValueError("chat attachments must be an array of at most 16 imports")
        validated = [
            self._jailed_import.validate_attachment(raw) for raw in attachment_values
        ]
        attachments = [attachment.to_json() for attachment, _path in validated]
        user_event: dict[str, object] = {"text": text}
        if attachments:
            user_event["attachments"] = attachments
        _ = self._emit("message.user", user_event)
        progress_id = f"turn:{self._session_id}"
        _ = self._emit(
            "progress.updated",
            {
                "progress_id": progress_id,
                "summary": "응답을 준비하고 있습니다.",
                "status": "working",
                "ui_state": "pending",
            },
        )
        pieces: list[str] = []

        def on_text(piece: str) -> None:
            pieces.append(piece)
            _ = self._emit("message.assistant.delta", {"text": piece})

        runtime_text = text
        if validated:
            lines = [
                f"- {attachment.display_name}: imports/{attachment.jail_name}"
                for attachment, _path in validated
            ]
            runtime_text += (
                "\n\nAttached workspace imports (validated):\n" + "\n".join(lines)
            )
        if self._pending_approval_context is not None:
            runtime_text = (
                f"{self._pending_approval_context}\n\n{runtime_text}"
            )
        session = self._get_session()
        try:
            reply = session.ask(runtime_text, on_text=on_text)
        except LLMError as error:
            failure = provider_failure(error.kind)
            self._failed_intent_payload = (
                {
                    "text": text,
                    **({"attachments": attachments} if attachments else {}),
                }
                if failure.retryable
                else None
            )
            event_payload: dict[str, object] = {
                "summary": failure.summary,
                "status": "failed",
                "ui_state": "failed",
                "refusal_code": failure.refusal_code,
                "retryable": failure.retryable,
                "provider_kind": error.kind,
            }
            if error.status is not None:
                event_payload["provider_status"] = error.status
            _ = self._emit("progress.updated", event_payload)
            raise
        except (OSError, RuntimeError, ValueError):
            # Expected runtime failures get bounded product copy, then re-raise.
            self._failed_intent_payload = {
                "text": text,
                **({"attachments": attachments} if attachments else {}),
            }
            _ = self._emit(
                "progress.updated",
                {
                    "progress_id": progress_id,
                    "summary": (
                        "응답을 완료하지 못했습니다. 잠시 후 다시 시도하세요."
                    ),
                    "status": "failed",
                    "ui_state": "failed",
                    "refusal_code": "E_RUNTIME",
                    "retryable": True,
                },
            )
            raise
        final = reply or "".join(pieces)
        _ = self._emit(
            "progress.updated",
            {
                "progress_id": progress_id,
                "summary": "응답을 완료했습니다.",
                "status": "succeeded",
                "ui_state": "succeeded",
            },
        )
        _ = self._emit("message.assistant.completed", {"text": final})
        _ = transcripts.append_turn(
            "workspace", self._run_id, text, final, cfg=session.cfg
        )
        self._pending_approval_context = None
        self._failed_intent_payload = None
        result: dict[str, object] = {"reply": final}
        if attachments:
            result["attachments"] = attachments
        return result

    def _chat_steer(self, payload: dict[str, object]) -> dict[str, object]:
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("steer text must be non-empty")
        cleaned = text.strip()
        if not self._get_session().steer(cleaned):
            raise ValueError("active runtime cannot be steered")
        _ = self._emit("turn.steered", {"text": cleaned})
        return {"steered": True}

    def _chat_retry(self, _payload: dict[str, object]) -> dict[str, object]:
        payload = self._failed_intent_payload
        if payload is None:
            raise ValueError("no failed intent to retry")
        return self._chat_send(dict(payload))

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
        _ = self._emit(
            "progress.updated",
            {
                "summary": "응답 생성을 중단했습니다.",
                "status": "interrupted",
                "ui_state": "paused",
            },
        )
        return {"interrupted": True}

    def _chat_resume(self, _payload: dict[str, object]) -> dict[str, object]:
        session = self._get_session()
        session.abort.clear()
        _ = self._emit("turn.resumed", {})
        return {"resumed": True}

    def _file_import(self, payload: dict[str, object]) -> dict[str, object]:
        imported = self._jailed_import.import_file(payload)
        reference = cast(dict[str, object], imported["reference"])
        display_name = reference.get("display_name")
        suffix = (
            Path(display_name).suffix.casefold()
            if isinstance(display_name, str)
            else ""
        )
        if suffix not in _REGISTERED_IMPORT_SUFFIXES:
            return imported
        _attachment, source = self._jailed_import.validate_attachment(reference)
        registered = self.surface_authority.office.register_import(reference, source)
        result = {
            "reference": reference,
            "artifact": registered["artifact"],
            "receipt": imported["receipt"],
        }
        _ = self._emit("office.updated", {"surface": "office", "result": result})
        return result

    def _office_job_request(self, payload: dict[str, object]) -> dict[str, object]:
        if "format" in payload:
            return self._office_creation_job_request(payload)
        from ..office.coordinator import (
            OfficeCaller,
            OfficeCoordinator,
            OfficeMutationRequest,
        )
        from ..office.progress import office_progress_sink

        required = {"request", "source", "outcome", "operations", "destination"}
        optional = {"overwrite_approved", "diff_id"}
        if not required <= set(payload) or set(payload) - required - optional:
            raise ValueError(
                "office.job_request payload does not match the canonical contract"
            )
        request = payload["request"]
        source = payload["source"]
        outcome = payload["outcome"]
        operations = payload["operations"]
        destination = payload["destination"]
        overwrite_approved = payload.get("overwrite_approved", False)
        diff_id = payload.get("diff_id")
        if not isinstance(request, str) or not request:
            raise ValueError("office.job_request request must be non-empty")
        if not isinstance(source, dict) or any(
            not isinstance(key, str) for key in cast(dict[object, object], source)
        ):
            raise ValueError("office.job_request source must be an object")
        if not isinstance(outcome, str) or not outcome:
            raise ValueError("office.job_request outcome must be non-empty")
        if not isinstance(operations, list) or not operations:
            raise ValueError("office.job_request operations must be a non-empty array")
        parsed_operations: list[Mapping[str, object]] = []
        for operation in cast(list[object], operations):
            if not isinstance(operation, dict) or any(
                not isinstance(key, str)
                for key in cast(dict[object, object], operation)
            ):
                raise ValueError("office.job_request operations must contain objects")
            parsed_operations.append(cast(dict[str, object], operation))
        if not isinstance(destination, str) or not destination:
            raise ValueError("office.job_request destination must be non-empty")
        if not isinstance(overwrite_approved, bool):
            raise ValueError("office.job_request overwrite_approved must be boolean")
        if diff_id is not None and (
            not isinstance(diff_id, str) or not diff_id
        ):
            raise ValueError("office.job_request diff_id must be non-empty")
        client_source = cast(dict[str, object], source)
        source_mapping = self.surface_authority.office.registered_document(
            client_source.get("artifact_id"),
            client_source.get("uri"),
        )

        approval = OfficeCoordinator(
            OfficeCaller(
                allowlist_root=self._workspace_root,
                actor=f"native:{self._session_id}",
            ),
            on_transition=office_progress_sink(self.runtime_event),
        ).request(
            OfficeMutationRequest(
                request_text=request,
                source=source_mapping,
                outcome=outcome,
                operations=tuple(parsed_operations),
                destination=Path(destination),
                overwrite_approved=overwrite_approved,
            )
        )
        source_filename = cast(str, source_mapping["source_filename"])
        approval["diff_id"] = diff_id or f"diff-{approval['job_id']}"
        approval["source_filename"] = source_filename
        approval["rejection_result"] = (
            "거부하면 원본은 변경되지 않으며 새 파일도 저장되지 않습니다."
        )
        semantic_summaries = cast(
            list[PreviewSummary],
            approval["semantic_summaries"],
        )
        description = format_preview_replacements(semantic_summaries)
        queued = approvals.propose(
            category="office_job",
            title=f"Office 변경: {outcome}",
            description=description,
            payload=approval,
            cfg={},
            origin=f"native:{self._session_id}",
        )
        approval_id = cast(str, queued["id"])
        _ = self._emit(
            "approval.requested",
            {
                "approval_id": approval_id,
                "summary": queued.get("title", f"Office 변경: {outcome}"),
                "description": description,
                "category": "office_job",
                "status": "pending",
                "risk": risk.risk_for("office_job"),
                "sealed": bool(approval["proposal_digest"]),
                "decided": False,
                "requester": approval["proposer"],
                "rejection_result": approval["rejection_result"],
                "job_id": approval["job_id"],
                "diff_id": approval["diff_id"],
                "proposal_digest": approval["proposal_digest"],
                "authority_digest": approval["authority_digest"],
                "destination": approval["destination"],
                "overwrite_approved": approval["overwrite_approved"],
                "source_filename": source_filename,
            },
        )
        return {**queued, "category": "office_job", "approval": approval}

    def _office_creation_job_request(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        from ..office.create_approval import (
            OfficeCreationCaller,
            OfficeCreationCoordinator,
            OfficeCreationRequest,
        )
        from ..office.errors import DocumentError, DocumentErrorCode

        required = {
            "request",
            "format",
            "content",
            "outcome",
            "destination",
        }
        optional = {"overwrite_approved"}
        if not required <= set(payload) or set(payload) - required - optional:
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "office_create",
                "Office creation job request fields changed",
            )
        request_text = payload["request"]
        outcome = payload["outcome"]
        destination = payload["destination"]
        if (
            not isinstance(request_text, str)
            or not request_text.strip()
            or not isinstance(outcome, str)
            or not outcome.strip()
            or not isinstance(destination, str)
            or not destination.strip()
        ):
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "office_create",
                "Office creation request, outcome, and destination are required",
            )
        if payload["format"] != "docx":
            raise DocumentError(
                DocumentErrorCode.UNSUPPORTED_FORMAT,
                "office_create",
                "Office creation job request currently supports DOCX only",
            )
        raw_content = payload["content"]
        if not isinstance(raw_content, dict) or set(raw_content) not in ({"paragraphs"}, {"business_template"}):
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "office_create",
                "DOCX creation content fields changed",
            )
        raw_paragraphs = cast(object, raw_content.get("paragraphs", ()))
        if not isinstance(raw_paragraphs, Sequence) or isinstance(
            raw_paragraphs,
            (str, bytes),
        ):
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "office_create",
                "DOCX creation paragraphs must be an array",
            )
        if not all(isinstance(paragraph, str) for paragraph in raw_paragraphs):
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "office_create",
                "DOCX creation paragraphs must be strings",
            )
        overwrite_approved = payload.get("overwrite_approved", False)
        if not isinstance(overwrite_approved, bool):
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "office_create",
                "overwrite_approved must be a boolean",
            )
        paragraphs = tuple(cast("str", paragraph) for paragraph in raw_paragraphs)
        approval = OfficeCreationCoordinator(
            OfficeCreationCaller(
                allowlist_root=self._workspace_root,
                actor=f"native:{self._session_id}",
            )
        ).request(OfficeCreationRequest(
            request_text=request_text,
            paragraphs=paragraphs,
            outcome=outcome,
            destination=Path(destination),
            overwrite_approved=overwrite_approved,
            content=raw_content if "business_template" in raw_content else None,
        ))
        description = (
            f"DOCX 문서를 {'업무 양식으로' if not paragraphs else f'{len(paragraphs)}개 단락으로'} 생성합니다: "
            f"{approval['destination']}."
        )
        queued = approvals.propose(
            category="office_create",
            title=f"Office 문서 생성: {outcome}",
            description=description,
            payload=approval,
            cfg={},
            origin=f"native:{self._session_id}",
        )
        approval_id = cast(str, queued["id"])
        _ = self._emit(
            "approval.requested",
            {
                "approval_id": approval_id,
                "kind": "approval",
                "summary": queued["title"],
                "description": description,
                "category": "office_create",
                "status": "pending",
                "risk": risk.risk_for("office_create"),
                "sealed": bool(approval["creation_digest"]),
                "decided": False,
                "requester": approval["proposer"],
                "rejection_result": (
                    "거부하면 저장 위치에 파일을 만들지 않습니다."
                ),
                "job_id": approval["job_id"],
                "creation_digest": approval["creation_digest"],
                "authority_digest": approval["authority_digest"],
                "destination": approval["destination"],
                "overwrite_approved": approval["overwrite_approved"],
            },
        )
        return {**queued, "category": "office_create", "approval": approval}

    def _office_create_request(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        from ..office.create_approval import (
            OfficeCreationCaller,
            OfficeCreationCoordinator,
            OfficeCreationRequest,
        )
        from ..office.errors import DocumentError, DocumentErrorCode

        if set(payload) != {"format", "content", "output_name"}:
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "office_create",
                "native Office creation payload fields changed",
            )
        if payload.get("format") != "docx":
            raise DocumentError(
                DocumentErrorCode.UNSUPPORTED_FORMAT,
                "office_create",
                "native Office creation currently supports DOCX only",
            )
        raw_content = payload.get("content")
        if not isinstance(raw_content, dict):
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "office_create",
                "Office creation content must be an object",
            )
        if set(raw_content) not in ({"paragraphs"}, {"business_template"}):
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "office_create",
                "DOCX creation content fields changed",
            )
        raw_paragraphs = cast(object, raw_content.get("paragraphs", ()))
        if not isinstance(raw_paragraphs, Sequence) or isinstance(
            raw_paragraphs,
            (str, bytes),
        ):
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "office_create",
                "DOCX creation paragraphs must be an array",
            )
        paragraphs: list[str] = []
        for paragraph in raw_paragraphs:
            if not isinstance(paragraph, str):
                raise DocumentError(
                    DocumentErrorCode.INVALID_INPUT,
                    "office_create",
                    "DOCX creation paragraphs must be strings",
                )
            paragraphs.append(paragraph)
        output_name = payload.get("output_name")
        if not isinstance(output_name, str):
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "office_create",
                "Office creation output_name must be a string",
            )
        approval = OfficeCreationCoordinator(
            OfficeCreationCaller(
                allowlist_root=self._workspace_root,
                actor=f"native:{self._session_id}",
            )
        ).request(OfficeCreationRequest(
            request_text=f"Create a new DOCX document at {output_name}",
            paragraphs=tuple(paragraphs),
            outcome=f"Create {output_name}",
            destination=self._workspace_root / output_name,
            content=raw_content if "business_template" in raw_content else None,
        ))
        description = (
            f"DOCX 문서를 {'업무 양식으로' if not paragraphs else f'{len(paragraphs)}개 단락으로'} 생성합니다: "
            f"{approval['destination']}."
        )
        queued = approvals.propose(
            category="office_create",
            title=f"Office 문서 생성: {output_name}",
            description=description,
            payload=approval,
            cfg={},
            origin=f"native:{self._session_id}",
        )
        _ = self._emit(
            "approval.requested",
            {
                "id": queued["id"],
                "kind": "approval",
                "summary": queued["title"],
                "description": description,
                "category": "office_create",
                "status": "pending",
                "risk": risk.risk_for("office_create"),
                "sealed": bool(approval["creation_digest"]),
                "decided": False,
                "requester": approval["proposer"],
                "rejection_result": (
                    "거부하면 저장 위치에 파일을 만들지 않습니다."
                ),
                "creation_digest": approval["creation_digest"],
                "authority_digest": approval["authority_digest"],
                "destination": approval["destination"],
                "overwrite_approved": approval["overwrite_approved"],
            },
        )
        return {**queued, "category": "office_create", "approval": approval}

    def _office_rollback_request(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        from ..office.rollback_approval import request_rollback

        if set(payload) != {"receipt_ref"}:
            raise ValueError(
                "office.rollback_request requires only receipt_ref"
            )
        receipt_ref = payload["receipt_ref"]
        if not isinstance(receipt_ref, str):
            raise ValueError("office.rollback_request receipt_ref is required")
        return request_rollback(
            job_id_from_receipt_ref(receipt_ref),
            origin=f"native:{self._session_id}",
        )

    def _approval_answer(self, payload: dict[str, object]) -> dict[str, object]:
        if set(payload) - {"approval_id", "decision", "reason"}:
            raise ValueError("approval.answer payload has unsupported fields")
        approval_id = payload.get("approval_id")
        decision = payload.get("decision")
        if not isinstance(approval_id, str):
            raise TypeError("approval_id is required")
        approval_record = store.get_pending(approval_id)
        result = approval_authority.decide(
            approval_id,
            decision=str(decision),
            reason=str(payload.get("reason") or ""),
            on_event=self.runtime_event,
        )
        event_payload: dict[str, object] = {
            "approval_id": approval_id,
            "decision": str(decision),
            "outcome": str(result["outcome"]),
        }
        receipt = result.get("receipt")
        receipt_projection: OfficeReceiptProjection | None = None
        if isinstance(receipt, str):
            event_payload["receipt"] = receipt
            if approval_record is not None:
                receipt_projection = OfficeReceiptProjection.from_result(
                    approval_id,
                    cast(dict[str, object], approval_record),
                    receipt,
                )
        if receipt_projection is not None:
            projected_payload = receipt_projection.event_payload()
            for field in (
                "receipt_ref",
                "destination",
                "issued_at",
                "expires_at",
                "backup_exists",
                "validation_summary",
                "visual_validation_summary",
            ):
                event_payload[field] = projected_payload[field]
            result["receipt_ref"] = receipt_projection.receipt_ref
        follow_up_approval_id = result.get("follow_up_approval_id")
        if isinstance(follow_up_approval_id, str):
            event_payload["follow_up_approval_id"] = follow_up_approval_id
            question = result.get("question")
            if isinstance(question, str):
                event_payload["question"] = question
        _ = self._emit("approval.answered", event_payload)
        if receipt_projection is not None:
            _ = self._emit(
                "receipt.recorded",
                receipt_projection.event_payload(),
            )
        if isinstance(follow_up_approval_id, str):
            from .approval_projection import approval_item

            follow_up = store.get_pending(follow_up_approval_id)
            if follow_up is not None:
                follow_up_projection = approval_item(follow_up)
                _ = self._emit(
                    "approval.requested",
                    {
                        **follow_up_projection,
                        "approval_id": follow_up_approval_id,
                    },
                )
        error = result.get("error")
        self._pending_approval_context = approval_turn_context(
            approval_id,
            str(result["outcome"]),
            receipt_projection,
            str(error) if isinstance(error, str) else None,
        )
        return {str(key): value for key, value in result.items()}

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
