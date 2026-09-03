"""Admission and command-to-model normalization for gateway turns."""

from __future__ import annotations

from dataclasses import replace

from .. import neurosis
from .turn_support import (
    PRIVILEGED_COMMANDS,
    UNTRUSTED_CHANNEL_REPLY,
    TurnContract,
    conversation_session_id,
    match_command,
)
from .turn_types import Admitted, AdmissionOutcome, GatewayTurn, Rejected, TurnRequest


def admit_turn(
    gateway: GatewayTurn,
    channel: str,
    chat_id: str,
    text: str,
    sender_id: str | None,
) -> AdmissionOutcome:
    normalized = (text or "").strip()
    if not normalized:
        return Rejected("")
    if not TurnContract.channel_trusted(gateway, channel, chat_id, sender_id):
        print(f"[gateway] denied untrusted {channel}:{chat_id}", flush=True)
        if normalized == "/omo" or normalized.startswith("/omo "):
            return Rejected(
                "OMO control is restricted to configured Telegram chat IDs."
            )
        return Rejected(UNTRUSTED_CHANNEL_REPLY)

    command, command_arg = match_command(normalized)
    if command in PRIVILEGED_COMMANDS and not TurnContract.command_trusted(
        gateway, channel
    ):
        return Rejected(
            "This command is restricted. Set "
            + "channels.telegram.allowed_chat_ids so only you can run "
            + "privileged commands."
        )
    request = TurnRequest(
        channel=channel,
        chat_id=str(chat_id),
        text=normalized,
        key=(channel, str(chat_id)),
        session_id=conversation_session_id(channel, str(chat_id)),
        command=command,
        command_arg=command_arg,
        display_text=normalized,
        skill_query=normalized,
        sender_id=str(sender_id).strip() if sender_id is not None else None,
    )
    return _prepare_neurosis(gateway, request)


def _prepare_neurosis(gateway: GatewayTurn, request: TurnRequest) -> AdmissionOutcome:
    if request.command != "neurosis":
        return Admitted(request)

    resolution = None
    kept: list[str] = []
    for token in request.command_arg.split():
        if token in ("--quick", "--standard", "--deep"):
            resolution = token[2:]
        else:
            kept.append(token)
    idea_arg = " ".join(kept)
    # seed_or_resume is shared read-modify-write state. Keep it under the same
    # global lock, but leave the model turn outside that lock.
    with TurnContract.state_lock(gateway):
        seed = neurosis.seed_or_resume(
            idea_arg, cfg=dict(gateway.cfg), resolution=resolution
        )
    if seed is None:
        return Rejected(
            "아이디어를 함께 주세요: /neurosis <모호한 아이디어> "
            + "(진행 중인 인터뷰가 있으면 /neurosis 만으로 재개)."
        )
    display_text = idea_arg or "/neurosis (resume)"
    return Admitted(
        replace(
            request,
            text=neurosis.start_prompt(seed),
            display_text=display_text,
            skill_query=f"neurosis {display_text}",
            command=None,
        )
    )
