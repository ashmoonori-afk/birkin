"""Telegram workflow proposals, approval resume, and long-run heartbeat."""

from __future__ import annotations

import json
import threading

from birkin import store
from birkin.gateway import core, workflow
from birkin.gateway.channels import telegram
from birkin.gateway.channels.telegram import TelegramChannel, _Streamer


def _proposal() -> workflow.WorkflowProposal:
    return workflow.WorkflowProposal(
        title="저장소 개선",
        summary="두 단계로 안전하게 구현하고 검증합니다.",
        steps=("관련 경로 조사", "구현 후 테스트"),
    )


def test_parse_proposal_accepts_only_complete_envelope() -> None:
    # Given
    body = json.dumps({
        "title": "저장소 개선",
        "summary": "작업 계획입니다.",
        "steps": ["조사", "구현", "검증"],
    }, ensure_ascii=False)
    raw = f"{workflow.PROPOSAL_OPEN}{body}{workflow.PROPOSAL_CLOSE}"

    # When
    proposal = workflow.parse_proposal(raw)

    # Then
    assert proposal == workflow.WorkflowProposal(
        title="저장소 개선",
        summary="작업 계획입니다.",
        steps=("조사", "구현", "검증"),
    )
    assert workflow.parse_proposal(raw + " trailing") is None
    assert workflow.parse_proposal(
        f'{workflow.PROPOSAL_OPEN}{{"title": 1}}{workflow.PROPOSAL_CLOSE}'
    ) is None


def test_approved_workflow_is_bound_to_chat_and_builds_resume_prompt(
        tmp_path, monkeypatch) -> None:
    # Given
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    aid = workflow.queue_proposal(_proposal(), "원래 작업", "42")

    # When
    denied = workflow.resolve_proposal(
        aid,
        "99",
        approve=True,
        actor_id="human:telegram:42",
        via="gateway:telegram",
    )
    approved = workflow.resolve_proposal(
        aid,
        "42",
        approve=True,
        actor_id="human:telegram:42",
        via="gateway:telegram",
    )

    # Then
    assert denied.resume_prompt is None
    assert "채팅" in denied.message
    assert approved.resume_prompt is not None
    assert workflow.APPROVED_OPEN in approved.resume_prompt
    assert "원래 작업" in approved.resume_prompt
    assert "관련 경로 조사" in approved.resume_prompt
    resolved = store.get_pending(aid)
    assert resolved["status"] == "claimed"
    assert resolved["approved_by"] == "human:telegram:42"
    assert resolved["approved_via"] == "gateway:telegram"


def test_telegram_execution_policy_has_in_chat_delivery_contract() -> None:
    # Given
    policy = core._TELEGRAM_EXECUTION_POLICY

    # When
    open_count = policy.count(workflow.DELIVERY_OPEN)
    close_count = policy.count(workflow.DELIVERY_CLOSE)

    # Then
    assert open_count == 1
    assert close_count == 1
    assert policy.index(workflow.DELIVERY_OPEN) < policy.index(
        workflow.DELIVERY_CLOSE
    )


def test_rejected_workflow_never_builds_resume_prompt(tmp_path, monkeypatch) -> None:
    # Given
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    aid = workflow.queue_proposal(_proposal(), "원래 작업", "42")

    # When
    rejected = workflow.resolve_proposal(
        aid,
        "42",
        approve=False,
        actor_id="human:telegram:42",
        via="gateway:telegram",
    )

    # Then
    assert rejected.resume_prompt is None
    assert rejected.message.startswith("❌")
    resolved = store.get_pending(aid)
    assert resolved["status"] == "rejected"
    assert resolved["rejected_by"] == "human:telegram:42"
    assert resolved["rejected_via"] == "gateway:telegram"


def test_streamer_holds_workflow_envelope_until_buttons_render() -> None:
    # Given
    sent: list[str] = []
    streamer = _Streamer(
        lambda text: sent.append(text) or "1",
        lambda _mid, _text: True,
        min_first=1,
    )

    # When
    streamer.feed(workflow.PROPOSAL_OPEN[:8])
    streamer.feed(workflow.PROPOSAL_OPEN[8:] + '{"title":"x"}')

    # Then
    assert sent == []


def test_run_turn_renders_proposal_as_one_button_message(
        tmp_path, monkeypatch) -> None:
    # Given
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    body = json.dumps({
        "title": "긴 작업",
        "summary": "승인 후 실행합니다.",
        "steps": ["계획", "실행"],
    }, ensure_ascii=False)
    reply = f"{workflow.PROPOSAL_OPEN}{body}{workflow.PROPOSAL_CLOSE}"

    class _Gateway:
        pending_hard_restart = False

        @staticmethod
        def handle(_channel, _chat_id, _text, on_text=None):
            if on_text:
                on_text(reply)
            return reply

    channel = TelegramChannel("token", allowed_chat_ids=["42"])
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        channel, "_keep_typing",
        lambda _chat_id, _stop, _progress=None: None,
    )
    monkeypatch.setattr(
        channel,
        "_call",
        lambda method, params, timeout=60: (
            calls.append((method, params))
            or {"ok": True, "result": {"message_id": 7}}
        ),
    )

    # When
    channel._run_turn(_Gateway(), "42", "오래 걸리는 작업", 1)

    # Then
    sent = [params for method, params in calls if method == "sendMessage"]
    assert len(sent) == 1
    assert workflow.PROPOSAL_OPEN not in sent[0]["text"]
    assert "reply_markup" in sent[0]
    pending = store.list_pending()
    assert len(pending) == 1 and pending[0]["category"] == "workflow"


def test_ultrawork_preface_renders_once_with_workflow_card(
        tmp_path, monkeypatch) -> None:
    # Given
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    body = json.dumps({
        "title": "Tokscale 제출 실행",
        "summary": "승인 후 정확한 명령만 실행합니다.",
        "steps": ["제출 명령 확인", "승인 후 실행"],
    }, ensure_ascii=False)
    reply = (
        "ULTRAWORK MODE ENABLED!\n\n"
        f"{workflow.PROPOSAL_OPEN}{body}{workflow.PROPOSAL_CLOSE}"
    )

    class _Gateway:
        pending_hard_restart = False

        @staticmethod
        def handle(_channel, _chat_id, _text, on_text=None):
            if on_text:
                on_text(reply)
            return reply

    channel = TelegramChannel("token", allowed_chat_ids=["42"])
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        channel, "_keep_typing",
        lambda _chat_id, _stop, _progress=None: None,
    )
    monkeypatch.setattr(
        channel,
        "_call",
        lambda method, params, timeout=60: (
            calls.append((method, params))
            or {"ok": True, "result": {"message_id": 7}}
        ),
    )

    # When
    channel._run_turn(_Gateway(), "42", "Tokscale 제출해줘", 1)

    # Then
    sent = [params for method, params in calls if method == "sendMessage"]
    assert len(sent) == 1
    assert sent[0]["text"].count("ULTRAWORK MODE ENABLED!") == 1
    assert workflow.PROPOSAL_OPEN not in sent[0]["text"]
    assert "reply_markup" in sent[0]


def test_workflow_proposal_is_an_html_safe_approval_card(
        tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    proposal = workflow.WorkflowProposal(
        title="<b>Kaggle 보안 에이전트 대회</b>",
        summary="규칙 & 데이터를 확인합니다.",
        steps=("규칙 <확인>", "기준선 & 검증"),
    )
    channel = TelegramChannel("token", allowed_chat_ids=["42"])
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        channel,
        "_call",
        lambda method, params, timeout=60: (
            calls.append((method, params))
            or {"ok": True, "result": {"message_id": 7}}
        ),
    )

    channel._send_workflow_proposal("42", proposal, "원래 요청")

    sent = [params for method, params in calls if method == "sendMessage"]
    assert len(sent) == 1
    assert sent[0]["parse_mode"] == "HTML"
    assert "<b>Kaggle" not in sent[0]["text"]
    assert "&lt;b&gt;Kaggle" in sent[0]["text"]
    assert "&amp;" in sent[0]["text"]
    assert "reply_markup" in sent[0]


def test_workflow_button_acknowledges_then_resumes_same_chat(
        tmp_path, monkeypatch) -> None:
    # Given
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    aid = workflow.queue_proposal(_proposal(), "원래 작업", "42")
    channel = TelegramChannel("token", allowed_chat_ids=["42"])
    calls: list[tuple[str, dict]] = []
    resumed: list[tuple[str, str, int]] = []
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(
        channel,
        "_call",
        lambda method, params, timeout=60: (
            calls.append((method, params)) or {"ok": True}
        ),
    )
    def run_turn(
        _gateway,
        chat_id,
        text,
        offset,
        workflow_id=None,
    ) -> None:
        resumed.append((chat_id, text, offset))
        started.set()
        assert release.wait(timeout=2)

    monkeypatch.setattr(channel, "_run_turn", run_turn)
    callback = {
        "id": "cb-work",
        "data": f"apv:{aid}",
        "from": {"id": 42},
        "message": {
            "chat": {"id": 42},
            "message_id": 9,
            "text": "🧭 저장소 개선",
        },
    }

    # When
    worker = None
    try:
        channel._handle_callback(object(), callback, offset=17)
        assert started.wait(timeout=2)
        worker = channel._workers["42"]
    finally:
        release.set()
        if worker is not None:
            worker.join(timeout=2)
            assert not worker.is_alive()

    # Then
    methods = [method for method, _params in calls]
    assert methods.index("answerCallbackQuery") < methods.index("editMessageText")
    assert resumed and resumed[0][0] == "42" and resumed[0][2] == 17
    assert workflow.APPROVED_OPEN in resumed[0][1]
    resolved = store.get_pending(aid)
    assert resolved["approved_by"] == "human:telegram:42"
    assert resolved["approved_via"] == "gateway:telegram"


def test_workflow_rejection_callback_persists_telegram_resolver(
        tmp_path, monkeypatch) -> None:
    # Given
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    aid = workflow.queue_proposal(_proposal(), "원래 작업", "42")
    channel = TelegramChannel("token", allowed_chat_ids=["42"])
    monkeypatch.setattr(
        channel,
        "_call",
        lambda *_args, **_kwargs: {"ok": True},
    )
    callback = {
        "id": "cb-reject",
        "data": f"rej:{aid}",
        "from": {"id": 42},
        "message": {"chat": {"id": 42}, "message_id": 9, "text": "proposal"},
    }

    # When
    channel._handle_callback(object(), callback)

    # Then
    resolved = store.get_pending(aid)
    assert resolved["status"] == "rejected"
    assert resolved["rejected_by"] == "human:telegram:42"
    assert resolved["rejected_via"] == "gateway:telegram"


def test_long_turn_heartbeat_updates_one_message_and_cleans_it_up(
        monkeypatch) -> None:
    # Given
    class _Clock:
        now = 0.0

        def __call__(self) -> float:
            return self.now

    class _Stop:
        def __init__(self, clock: _Clock) -> None:
            self.clock = clock
            self.waits = 0

        def is_set(self) -> bool:
            return self.waits >= 5

        def wait(self, seconds: float) -> bool:
            self.clock.now += seconds
            self.waits += 1
            return self.is_set()

    clock = _Clock()
    stop = _Stop(clock)
    channel = TelegramChannel("token", allowed_chat_ids=["42"])
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(telegram.time, "monotonic", clock)
    monkeypatch.setattr(channel, "_HEARTBEAT_INTERVAL", 8.0)
    monkeypatch.setattr(
        channel,
        "_call",
        lambda method, params, timeout=60: (
            calls.append((method, params))
            or {"ok": True, "result": {"message_id": 11}}
        ),
    )

    # When
    channel._keep_typing("42", stop)

    # Then
    methods = [method for method, _params in calls]
    assert "sendMessage" in methods
    assert "editMessageText" in methods
    assert methods[-1] == "deleteMessage"
