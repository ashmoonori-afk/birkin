"""Gateway model-turn recovery, durable completion, and lease release."""

from __future__ import annotations

import time

from .. import store
from ..codex_session import CodexTurnTimeout
from .turn_support import (
    TURN_ERROR_REPLY,
    TURN_MOIRAI_RECOVERY_ERROR_REPLY,
    TURN_MOIRAI_RECOVERY_PROPOSED_REPLY,
    TURN_PARTIAL_SUFFIX,
    TurnContract,
)
from .turn_types import (
    ConversationKey,
    GatewayTurn,
    ProgressInfo,
    TurnLease,
    TurnRequest,
)

_RECOVERY_TITLE = "시간 초과된 작업 이어서 하기"
_RECOVERY_WHY = (
    "응답이 시간 제한에 걸려 멈춘 요청이에요. 승인하면 hard-task 워크플로우가 "
    "남은 작업을 할 일로 나눠 하나씩 처리하고 결과를 글로 보고합니다 "
    "(파일을 직접 고치지는 않아요)."
)
_RECOVERY_STEPS = (
    "남은 작업을 할 일 목록으로 나누기",
    "할 일을 하나씩 처리하고 확인하기",
    "결과를 한 번에 보고하기",
)


def recover_codex_timeout(
    gateway: GatewayTurn,
    request: TurnRequest,
    started: float,
    progress_seen: ProgressInfo,
    exc: CodexTurnTimeout,
) -> str:
    """Record the timeout, then PROPOSE the rest of the work -- never run it.

    A multi-agent hard task is the spawn path with no natural ceiling, so it
    stays behind a person: the recovery goes to the approval inbox (or runs
    at once only when the user opted in with ``auto_approve: ["moirai"]``),
    and only a channel with a trusted principal may propose it at all.
    """
    elapsed = time.monotonic() - started
    print(
        f"[gateway] {request.channel}:{request.chat_id} ✗ error after "
        + f"{elapsed:.1f}s: {exc}",
        flush=True,
    )
    partial = str(exc.partial or "").strip()
    from ..moirai import journal as moirai_journal

    activity = progress_seen.get("activity")
    event_count = activity if isinstance(activity, int) else 0
    moirai_journal.record_incident(
        kind="codex_timeout",
        channel=request.channel,
        chat_id=request.chat_id,
        elapsed_seconds=elapsed,
        partial_chars=len(partial),
        last_event_kind=str(
            progress_seen.get("active_kind") or progress_seen.get("last_kind") or ""
        ),
        event_count=event_count,
        detail=str(exc),
    )
    if not TurnContract.command_trusted(gateway, request.channel):
        reply = partial + TURN_PARTIAL_SUFFIX if partial else TURN_ERROR_REPLY
        TurnContract.record_failed_turn(
            gateway, request.display_text, reply, request.channel, request.chat_id
        )
        return reply
    try:
        queued = _queue_moirai_recovery(gateway, request, partial)
    except Exception as recovery_exc:
        print(
            f"[gateway] {request.channel}:{request.chat_id} ✗ Moirai recovery "
            + f"could not be queued: {recovery_exc}",
            flush=True,
        )
        TurnContract.record_failed_turn(
            gateway,
            request.display_text,
            TURN_MOIRAI_RECOVERY_ERROR_REPLY,
            request.channel,
            request.chat_id,
        )
        return TURN_MOIRAI_RECOVERY_ERROR_REPLY
    if queued.get("auto"):
        # The user opted in (auto_approve lists moirai): the run already
        # happened, and its rendered outcome is the reply.
        if queued.get("ok"):
            recovered = str(queued.get("result") or "")
        else:
            print(
                f"[gateway] {request.channel}:{request.chat_id} ✗ Moirai recovery "
                + f"auto-approval failed: {queued.get('result')}",
                flush=True,
            )
            recovered = TURN_MOIRAI_RECOVERY_ERROR_REPLY
    else:
        recovered = (
            TURN_MOIRAI_RECOVERY_PROPOSED_REPLY + "\n" + _approval_hint(request.channel)
        )
    reply = ((partial + "\n\n") if partial else "") + recovered
    TurnContract.record_failed_turn(
        gateway, request.display_text, reply, request.channel, request.chat_id
    )
    return reply


def _approval_hint(channel: str) -> str:
    if channel == "telegram":
        return "/pending 에서 승인 버튼을 눌러 주세요."
    return "Birkin 승인 목록에서 승인해 주세요."


def _queue_moirai_recovery(
    gateway: GatewayTurn, request: TurnRequest, partial: str
) -> dict[str, object]:
    from ..moirai import trigger as moirai_trigger

    recovery_task = request.display_text
    if partial:
        recovery_task += (
            "\n\nCodex가 중단되기 전 완료한 내용:\n"
            + partial
            + "\n\n완료된 내용은 반복하지 말고 남은 작업만 수행하라."
        )
    proposal = moirai_trigger.Proposal(
        title=_RECOVERY_TITLE,
        why=_RECOVERY_WHY,
        script="hard-task",
        roles=(),
        steps=_RECOVERY_STEPS,
    )
    return moirai_trigger.queue(
        proposal,
        task=recovery_task,
        cfg=dict(gateway.cfg),
        origin="gateway-timeout",
    )


def complete_turn(
    gateway: GatewayTurn,
    request: TurnRequest,
    persistent: bool,
    reply: str,
    started: float,
) -> None:
    elapsed = time.monotonic() - started
    print(
        f"[gateway] {request.channel}:{request.chat_id} » "
        + f"{len(reply or '')} chars in {elapsed:.1f}s",
        flush=True,
    )
    if TurnContract.autosave_trusted(gateway, request.channel):
        store.append_activity(
            f"gateway[{request.channel}:{request.chat_id}]: "
            + f"{request.display_text[:100]}"
        )
    if persistent and TurnContract.command_trusted(gateway, request.channel):
        TurnContract.record_turn(
            gateway.session,
            request.display_text,
            reply or "",
            review_skills=TurnContract.command_trusted(gateway, request.channel),
            session_id=request.session_id,
        )
    if TurnContract.autosave_trusted(gateway, request.channel):
        from .. import transcripts

        _ = transcripts.append_turn(
            request.channel,
            request.chat_id,
            request.display_text,
            reply or "",
            cfg=dict(gateway.cfg),
        )


def release_turn(gateway: GatewayTurn, key: ConversationKey, lease: TurnLease) -> None:
    if not lease.persistent:
        return
    try:
        with TurnContract.inflight_lock(gateway):
            inflight = TurnContract.inflight_owners(gateway)
            owners = inflight.get(key)
            if owners is not None:
                for index, owner in enumerate(owners):
                    if owner[0] is lease.token:
                        _ = owners.pop(index)
                        break
            if not owners:
                _ = inflight.pop(key, None)
    finally:
        TurnContract.release_session(gateway, key, lease.session)
