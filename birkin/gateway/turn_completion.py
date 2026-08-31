"""Gateway model-turn recovery, durable completion, and lease release."""

from __future__ import annotations

import time

from .. import store
from ..codex_session import CodexTurnTimeout
from .turn_support import TURN_MOIRAI_RECOVERY_ERROR_REPLY, TurnContract
from .turn_types import (
    ConversationKey,
    GatewayTurn,
    ProgressCallback,
    ProgressInfo,
    TurnLease,
    TurnRequest,
)


def recover_codex_timeout(
    gateway: GatewayTurn,
    request: TurnRequest,
    started: float,
    progress_seen: ProgressInfo,
    on_progress: ProgressCallback,
    exc: CodexTurnTimeout,
) -> str:
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
    try:
        recovered = _run_moirai_recovery(request, partial, on_progress)
    except Exception as recovery_exc:
        print(
            f"[gateway] {request.channel}:{request.chat_id} ✗ Moirai recovery "
            + f"failed: {recovery_exc}",
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
    reply = ((partial + "\n\n") if partial else "") + recovered
    TurnContract.record_failed_turn(
        gateway, request.display_text, reply, request.channel, request.chat_id
    )
    return reply


def _run_moirai_recovery(
    request: TurnRequest, partial: str, on_progress: ProgressCallback
) -> str:
    from ..moirai import trigger as moirai_trigger

    seen = {"n": 0}

    def on_moirai_event(event: str, payload: ProgressInfo) -> None:
        if event != "moirai.phase" or on_progress is None:
            return
        seen["n"] += 1
        try:
            on_progress(
                {
                    "phase": str((payload or {}).get("title") or ""),
                    "activity": seen["n"],
                }
            )
        except Exception:
            pass

    recovery_task = request.display_text
    if partial:
        recovery_task += (
            "\n\nCodex가 중단되기 전 완료한 내용:\n"
            + partial
            + "\n\n완료된 내용은 반복하지 말고 남은 작업만 수행하라."
        )
    return moirai_trigger.run_approved(
        {"script": "hard-task", "task": recovery_task},
        on_event=on_moirai_event if on_progress is not None else None,
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
