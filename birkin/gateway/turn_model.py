"""Model-input preparation and persistent/nonpersistent turn execution."""

from __future__ import annotations

import time

from ..codex_session import CodexTurnTimeout
from .turn_completion import complete_turn, recover_codex_timeout
from .turn_model_session import (
    ModelContract as ModelContract,
    ModelSession as ModelSession,
    SkillState as SkillState,
    ask_model,
    ask_shared_session,
    skill_state,
)
from .turn_support import (
    TURN_ERROR_REPLY,
    TURN_INTERRUPTED_REPLY,
    TURN_PARTIAL_SUFFIX,
    TurnContract,
    anchor_short_followup,
    is_short_followup,
)
from .turn_types import (
    GatewayTurn,
    PreparedTurn,
    ProgressCallback,
    ProgressInfo,
    TextCallback,
    TurnLease,
    TurnRequest,
)
from .workflow import WORKFLOW_POLICY, is_running as workflow_is_running

_ask_model = ask_model
_ask_shared_session = ask_shared_session
_skill_state = skill_state

TELEGRAM_EXECUTION_POLICY = (
    "<gateway-execution-policy>\n"
    + WORKFLOW_POLICY
    + 'Keep this foreground turn responsive: inspect only files relevant to the request and run only targeted tests. Do not wait for a repository-wide test suite. If broader verification is warranted, start it as a detached background job, write its output and exit status to a receipt inside the workspace, and tell the user the receipt path.\nWhen the user explicitly asks you to send a generated file back through Telegram, create it inside the current workspace and append one standalone marker per file as the final line: <telegram-attachment path="relative/path.ext" />. Do not wrap the marker in a code fence, and never emit it before the file exists.\n</gateway-execution-policy>\n\n'
)


def run_model_turn(
    gateway: GatewayTurn,
    request: TurnRequest,
    lease: TurnLease,
    on_text: TextCallback,
    workflow_id: str | None,
    on_progress: ProgressCallback,
) -> str:
    started = time.monotonic()
    if lease.persistent:
        if lease.session is None:
            return TURN_ERROR_REPLY
        try:
            with TurnContract.inflight_lock(gateway):
                TurnContract.inflight_owners(gateway).setdefault(
                    request.key, []
                ).append((lease.token, lease.session, lease.interrupted))
        except RuntimeError as exc:
            elapsed = time.monotonic() - started
            print(
                f"[gateway] {request.channel}:{request.chat_id} ✗ error after "
                + f"{elapsed:.1f}s: {exc}",
                flush=True,
            )
            return TURN_ERROR_REPLY

    prepared = _prepare_model_input(
        gateway, request, lease.needs_seed, workflow_id, on_progress
    )
    print(
        f"[gateway] {request.channel}:{request.chat_id} « {request.display_text[:80]}",
        flush=True,
    )
    try:
        reply = _ask_model(gateway, request, lease, prepared, on_text)
    except CodexTurnTimeout as exc:
        return recover_codex_timeout(
            gateway, request, started, prepared.progress_seen, on_progress, exc
        )
    except Exception as exc:  # Model boundary returns a safe reply.
        elapsed = time.monotonic() - started
        print(
            f"[gateway] {request.channel}:{request.chat_id} ✗ error after "
            + f"{elapsed:.1f}s: {exc}",
            flush=True,
        )
        partial = str(getattr(exc, "partial", "") or "").strip()
        return partial + TURN_PARTIAL_SUFFIX if partial else TURN_ERROR_REPLY

    if lease.interrupted.is_set() and not reply:
        reply = TURN_INTERRUPTED_REPLY
    complete_turn(gateway, request, lease.persistent, reply, started)
    return reply or "(no reply)"


def _prepare_model_input(
    gateway: GatewayTurn,
    request: TurnRequest,
    needs_seed: bool,
    workflow_id: str | None,
    on_progress: ProgressCallback,
) -> PreparedTurn:
    text = request.text
    trusted_telegram = request.channel == "telegram" and TurnContract.command_trusted(
        gateway, request.channel
    )
    if trusted_telegram:
        text = _anchor_followup(gateway, request, text, needs_seed)
    approved_work = bool(
        trusted_telegram
        and workflow_id
        and workflow_is_running(workflow_id, request.chat_id)
    )
    if needs_seed and TurnContract.autosave_trusted(gateway, request.channel):
        from .. import transcripts

        tail = transcripts.read_recent(request.channel, request.chat_id)
        if tail:
            text = (
                "## 이전 대화 기록 (프로세스 재시작 전, 참고용)\n"
                + "아래는 이 대화의 저장된 최근 기록이다. 문맥 파악에만 "
                + "사용하고, 답변은 마지막 사용자 메시지에만 하라.\n\n"
                + tail
                + "\n\n## 현재 메시지\n\n"
                + text
            )
    if trusted_telegram:
        text = TELEGRAM_EXECUTION_POLICY + text

    progress_seen: ProgressInfo = {}

    def watch_progress(info: ProgressInfo) -> None:
        progress_seen.update(info or {})
        if on_progress is not None:
            on_progress(info)

    return PreparedTurn(
        text, trusted_telegram, approved_work, progress_seen, watch_progress
    )


def _anchor_followup(
    gateway: GatewayTurn,
    request: TurnRequest,
    text: str,
    needs_seed: bool,
) -> str:
    short_followup = is_short_followup(request.display_text)
    with TurnContract.state_lock(gateway):
        previous_request = ModelContract.previous_request(gateway, request.key)
    if short_followup and not previous_request and needs_seed:
        from .. import transcripts

        previous_request = next(
            (
                prior
                for prior in transcripts.read_recent_user_requests(
                    request.channel, request.chat_id
                )
                if not is_short_followup(prior)
            ),
            "",
        )
        if previous_request:
            with TurnContract.state_lock(gateway):
                ModelContract.remember_request_once(
                    gateway, request.key, previous_request
                )
    if short_followup:
        return (
            anchor_short_followup(text, previous_request) if previous_request else text
        )
    with TurnContract.state_lock(gateway):
        ModelContract.remember_request(gateway, request.key, request.display_text)
    return text
