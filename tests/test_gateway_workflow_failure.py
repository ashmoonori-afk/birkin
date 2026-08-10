from __future__ import annotations

from birkin import store
from birkin.gateway import workflow
from birkin.gateway.channels.telegram import TelegramChannel


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

    class _Gateway:
        pending_hard_restart = False

        @staticmethod
        def handle(_channel, _chat_id, _text, on_text=None, workflow_id=None):
            return ("⚠️ 문제가 생겨서 이번 메시지를 처리하지 못했어요. "
                    "잠시 후 다시 시도해 주세요.")

    channel = TelegramChannel("token", allowed_chat_ids=["42"], stream=False)
    channel._workflow_ids["42"] = aid
    monkeypatch.setattr(channel, "_keep_typing",
                        lambda _chat, _stop, _progress=None: None)
    monkeypatch.setattr(
        channel, "_call",
        lambda *_args, **_kwargs: {"ok": True, "result": {"message_id": 1}},
    )

    channel._run_turn(_Gateway(), "42", resolution.resume_prompt or "", 1, aid)

    assert store.get_pending(aid)["status"] == "error"


def test_approved_workflow_cannot_queue_another_proposal(
        tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    proposal = workflow.WorkflowProposal("work", "run it", ("execute",))
    aid = workflow.queue_proposal(proposal, "original", "42")
    resolution = workflow.resolve_proposal(aid, "42", approve=True)
    body = '{"title":"again","summary":"loop","steps":["retry"]}'
    reply = f"{workflow.PROPOSAL_OPEN}{body}{workflow.PROPOSAL_CLOSE}"

    class _Gateway:
        pending_hard_restart = False

        @staticmethod
        def handle(_channel, _chat_id, _text, on_text=None, workflow_id=None):
            return reply

    channel = TelegramChannel("token", allowed_chat_ids=["42"], stream=False)
    channel._workflow_ids["42"] = aid
    monkeypatch.setattr(channel, "_keep_typing",
                        lambda _chat, _stop, _progress=None: None)
    monkeypatch.setattr(
        channel, "_call",
        lambda *_args, **_kwargs: {"ok": True, "result": {"message_id": 1}},
    )

    channel._run_turn(_Gateway(), "42", resolution.resume_prompt or "", 1, aid)

    assert store.get_pending(aid)["status"] == "error"
    assert store.list_pending() == []
