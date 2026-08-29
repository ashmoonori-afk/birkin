"""Deterministic runtime adapter for real PTY workspace QA."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import final

from birkin import config, repl, statusline
from birkin.web import server
from birkin.workspace import WorkspaceEvent
from birkin.workspace.hub import EventSink
from script.qa.workspace_fixture_events import (
    emit_approval_request,
    emit_computer_update,
    emit_office_progress,
    emit_question_bundle,
)

SESSION_ID = "qa-terminal"


@final
class FixtureSession:
    def __init__(self) -> None:
        self.cfg: dict[str, object] = {
            "model": "fixture",
            "session_id": SESSION_ID,
            "web_port": 0,
        }
        self.skills = SimpleNamespace(skills={"qa": object()})
        self.memory = SimpleNamespace(vault=config.birkin_home() / "vault")
        self.agent = SimpleNamespace(
            legacy_client_name="fixture",
            on_event=None,
        )
        self.ctx = SimpleNamespace(shell_prompt_cb=None)
        self.abort = threading.Event()
        self.closed = False

    def close(self) -> None:
        self.closed = True


@final
class FixtureRuntimeWorkspaceAdapter:
    def __init__(self, _session_id: str, emit: EventSink) -> None:
        self._emit = emit
        self._session = FixtureSession()
        self._approval_pending = False

    def handlers(self) -> dict[str, object]:
        return {
            "chat.send": self._chat_send,
            "chat.interrupt": self._interrupt,
            "chat.resume": self._resume,
            "approval.answer": self._approval_answer,
            "question.answer": self._question_answer,
        }

    def runtime_session(self) -> FixtureSession:
        return self._session

    def close(self) -> None:
        self._session.close()

    def interrupt_now(self) -> None:
        self._session.abort.set()

    def _event(
        self,
        event_type: str,
        payload: dict[str, object],
    ) -> WorkspaceEvent:
        return self._emit(event_type, payload)

    def _chat_send(self, payload: dict[str, object]) -> dict[str, object]:
        text = str(payload.get("text") or "")
        _ = self._event("message.user", {"text": text})
        _ = self._event(
            "progress.updated",
            {
                "runtime_event": "subagent.start",
                "name": "fixture-research",
                "summary": "fixture task started",
            },
        )
        _ = self._event(
            "tool.started",
            {
                "runtime_event": "tool_start",
                "name": "fixture-tool",
                "summary": "fixture tool",
            },
        )
        _ = self._event(
            "tool.completed",
            {
                "runtime_event": "tool_end",
                "name": "fixture-tool",
                "summary": "fixture tool",
            },
        )
        if text == "office progress":
            emit_office_progress(self._event)
            return self._reply(
                "Office progress projected.",
                ("Office progress ", "projected."),
            )
        if text == "interrupt":
            return self._interruptible_reply()
        if text == "computer use":
            emit_computer_update(self._event)
            return self._reply(
                "Computer Use event projected.",
                ("Computer Use event ", "projected."),
            )
        if "approval" in text:
            approval_id = (
                "qa-approval-2" if "second" in text else "qa-approval"
            )
            self._approval_pending = True
            emit_approval_request(self._event, approval_id)
            return self._reply(
                "Approval required. Type approve to resume.",
                ("Approval required. ", "Type approve to resume."),
            )
        if text == "approve" and self._approval_pending:
            self._approval_pending = False
            _ = self._event(
                "approval.answered",
                {"approval_id": "qa-approval", "decision": "approve"},
            )
            return self._reply(
                "완료되었습니다 ✓ shared continuation",
                ("완료되었습니다 ✓ ", "shared continuation"),
            )
        if text == "inspect question evidence checkpoint":
            emit_question_bundle(self._event)
            return self._reply(
                "Question ready with file evidence and checkpoint.",
                ("Question ready with ", "file evidence and checkpoint."),
            )
        if text == "answer question: continue":
            _ = self._event(
                "question.answered",
                {
                    "question_id": "qa-question",
                    "summary": "Continue with the inspected evidence?",
                    "answer": "continue",
                    "ui_state": "succeeded",
                },
            )
            return self._reply(
                "Question answered: continue",
                ("Question answered: ", "continue"),
            )
        return self._reply(
            f"Echo complete 🧵: {text}",
            ("Echo complete 🧵: ", text),
        )

    def _interruptible_reply(self) -> dict[str, object]:
        self._session.abort.clear()
        _ = self._event(
            "message.assistant.delta",
            {"text": "interrupt-ready"},
        )
        if not self._session.abort.wait(timeout=10):
            raise TimeoutError("PTY did not deliver the interrupt event")
        _ = self._event("turn.interrupted", {"reason": "terminal-escape"})
        return self._reply(
            "Interrupted safely",
            (" — ", "Interrupted safely"),
        )

    def _reply(
        self,
        final: str,
        pieces: tuple[str, ...],
    ) -> dict[str, object]:
        for piece in pieces:
            _ = self._event("message.assistant.delta", {"text": piece})
        _ = self._event("message.assistant.completed", {"text": final})
        return {"reply": final}

    def _interrupt(self, _payload: dict[str, object]) -> dict[str, object]:
        self._session.abort.set()
        _ = self._event("turn.interrupted", {})
        return {"interrupted": True}

    def _resume(self, _payload: dict[str, object]) -> dict[str, object]:
        self._session.abort.clear()
        _ = self._event("turn.resumed", {})
        return {"resumed": True}

    def _approval_answer(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self._approval_pending = False
        _ = self._event(
            "approval.answered",
            {
                "approval_id": str(payload.get("approval_id") or ""),
                "decision": str(payload.get("decision") or ""),
                "receipt": "fixture approval executed",
            },
        )
        if str(payload.get("approval_id") or "") != "qa-approval":
            _ = self._event(
                "checkpoint.restored",
                {
                    "checkpoint_id": "a1b2c3d4",
                    "summary": "Before workspace inspection",
                    "ui_state": "succeeded",
                },
            )
        return self._reply(
            "완료되었습니다 ✓ shared continuation",
            ("완료되었습니다 ✓ ", "shared continuation"),
        )

    def _question_answer(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        question_id = str(payload.get("question_id") or "")
        answer = str(payload.get("answer") or "")
        _ = self._event(
            "question.answered",
            {
                "question_id": question_id,
                "summary": "Continue with the inspected evidence?",
                "answer": answer,
                "ui_state": "succeeded",
            },
        )
        return self._reply(
            f"Question answered: {answer}",
            ("Question answered: ", answer),
        )


def main() -> int:
    _ = setattr(
        server,
        "RuntimeWorkspaceAdapter",
        FixtureRuntimeWorkspaceAdapter,
    )
    statusline.render = lambda _cfg: "fixture · shared workspace connected"
    return repl.run(
        {
            "model": "fixture",
            "session_id": SESSION_ID,
            "web_port": 0,
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
