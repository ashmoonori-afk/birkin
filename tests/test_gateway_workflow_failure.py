from __future__ import annotations

from collections.abc import Callable
from typing import Any

from birkin import store
from birkin.gateway import workflow
from birkin.gateway.channels.telegram import TelegramChannel
from birkin.gateway.core import Gateway


class _ReplyGateway(Gateway):
    """Gateway double that answers every turn with one canned reply.

    Subclasses the real Gateway so the channel sees the production type and
    handle() signature; built through __new__ (like the other gateway tests)
    because driving one turn needs no config, session or warm-CLI pool.
    """

    _reply: str = ""

    @classmethod
    def with_reply(cls, reply: str) -> _ReplyGateway:
        gateway = cls.__new__(cls)
        gateway._reply = reply
        return gateway

    @property
    def pending_hard_restart(self) -> bool:
        return False

    def handle(self, channel: str, chat_id: str, text: str,
               on_text: Callable[[str], None] | None = None,
               workflow_id: str | None = None,
               on_progress: Callable[[dict[str, Any]], None] | None = None,
               ) -> str:
        return self._reply


def test_gateway_error_reply_marks_approved_workflow_as_error(
        tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    proposal = workflow.WorkflowProposal(
        title="실패 작업",
        summary="오류 상태를 기록합니다.",
        steps=("실행",),
    )
    aid = workflow.queue_proposal(proposal, "실패해줘", "42")
    resolution = workflow.resolve_proposal(aid, "42", approve=True)

    gateway = _ReplyGateway.with_reply(
        "⚠️ 문제가 생겨서 이번 메시지를 처리하지 못했어요. "
        "잠시 후 다시 시도해 주세요.")

    channel = TelegramChannel("token", allowed_chat_ids=["42"], stream=False)
    channel._workflow_ids["42"] = aid
    monkeypatch.setattr(channel, "_keep_typing",
                        lambda _chat, _stop, _progress=None: None)
    monkeypatch.setattr(
        channel, "_call",
        lambda *_args, **_kwargs: {"ok": True, "result": {"message_id": 1}},
    )

    channel._run_turn(gateway, "42", resolution.resume_prompt or "", 1, aid)

    pending = store.get_pending(aid)
    assert pending is not None
    assert pending["status"] == "error"


def test_approved_workflow_cannot_queue_another_proposal(
        tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    proposal = workflow.WorkflowProposal("work", "run it", ("execute",))
    aid = workflow.queue_proposal(proposal, "original", "42")
    resolution = workflow.resolve_proposal(aid, "42", approve=True)
    body = '{"title":"again","summary":"loop","steps":["retry"]}'
    reply = f"{workflow.PROPOSAL_OPEN}{body}{workflow.PROPOSAL_CLOSE}"

    gateway = _ReplyGateway.with_reply(reply)

    channel = TelegramChannel("token", allowed_chat_ids=["42"], stream=False)
    channel._workflow_ids["42"] = aid
    monkeypatch.setattr(channel, "_keep_typing",
                        lambda _chat, _stop, _progress=None: None)
    monkeypatch.setattr(
        channel, "_call",
        lambda *_args, **_kwargs: {"ok": True, "result": {"message_id": 1}},
    )

    channel._run_turn(gateway, "42", resolution.resume_prompt or "", 1, aid)

    pending = store.get_pending(aid)
    assert pending is not None
    assert pending["status"] == "error"
    assert store.list_pending() == []
