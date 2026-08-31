"""Typed model-session access and turn dispatch."""

from __future__ import annotations

from typing import Protocol, TypeAlias

from ..runtime import Session
from .turn_support import TurnContract, ask_session
from .turn_types import (
    AskSession,
    GatewayTurn,
    PreparedTurn,
    TextCallback,
    TurnLease,
    TurnRequest,
)

SkillState: TypeAlias = dict[str, int | set[str]]


class ModelContract(TurnContract, Protocol):
    """Public operations over gateway model-turn state."""

    @staticmethod
    def build_claude_session(gateway: GatewayTurn) -> AskSession:
        return gateway._build_claude_session(trusted=False)

    @staticmethod
    def previous_request(gateway: GatewayTurn, key: tuple[str, str]) -> str | None:
        return gateway._last_substantive_requests.get(key)

    @staticmethod
    def remember_request(gateway: GatewayTurn, key: tuple[str, str], text: str) -> None:
        gateway._last_substantive_requests[key] = text

    @staticmethod
    def remember_request_once(
        gateway: GatewayTurn, key: tuple[str, str], text: str
    ) -> None:
        _ = gateway._last_substantive_requests.setdefault(key, text)

    @staticmethod
    def chat_history(
        gateway: GatewayTurn, key: tuple[str, str]
    ) -> list[dict[str, object]]:  # noqa: OBJECT_OK - runtime message contract
        return gateway._chats.get(key, [])

    @staticmethod
    def save_chat_history(
        gateway: GatewayTurn,
        key: tuple[str, str],
        history: list[dict[str, object]],  # noqa: OBJECT_OK - runtime message contract
    ) -> None:
        gateway._chats[key] = history


class ModelSession(Session):
    """Typed access to the runtime session's CLI-turn preparation hook."""

    @staticmethod
    def prepare_cli_turn(
        session: Session,
        text: str,
        route_query: str,
        skill_state: SkillState | None,
        session_id: str,
        trusted: bool,
    ) -> str:
        return session._prepare_cli_turn(
            text,
            route_query=route_query,
            skill_state=skill_state,
            session_id=session_id,
            trusted=trusted,
        )


def skill_state(session: AskSession) -> SkillState:
    state: SkillState | None = getattr(session, "_birkin_skill_state", None)
    if state is None:
        state = {"revision": -1, "names": set()}
        setattr(session, "_birkin_skill_state", state)
    return state


def ask_model(
    gateway: GatewayTurn,
    request: TurnRequest,
    lease: TurnLease,
    prepared: PreparedTurn,
    on_text: TextCallback,
) -> str:
    untrusted_claude = (
        not TurnContract.command_trusted(gateway, request.channel)
        and gateway.cfg.get("provider") == "claude-cli"
    )
    if untrusted_claude and not lease.persistent:
        one_shot = ModelContract.build_claude_session(gateway)
        try:
            return ask_session(
                one_shot,
                ModelSession.prepare_cli_turn(
                    gateway.session,
                    prepared.text,
                    request.skill_query,
                    None,
                    request.session_id,
                    False,
                ),
                on_text=on_text,
                on_progress=prepared.watch_progress,
            )
        finally:
            one_shot.close()
    if lease.persistent:
        if lease.session is None:
            raise RuntimeError(  # noqa: GENERIC_ERR_OK - impossible lease invariant
                "persistent turn has no borrowed session"
            )
        session_skill_state = skill_state(lease.session)
        return ask_session(
            lease.session,
            ModelSession.prepare_cli_turn(
                gateway.session,
                prepared.text,
                request.skill_query,
                session_skill_state,
                request.session_id,
                TurnContract.command_trusted(gateway, request.channel),
            ),
            on_text=on_text,
            on_progress=prepared.watch_progress,
        )
    return ask_shared_session(gateway, request, prepared)


def ask_shared_session(
    gateway: GatewayTurn, request: TurnRequest, prepared: PreparedTurn
) -> str:
    # The non-persistent path swaps history on one shared session and therefore
    # remains serialized under the global lock.
    with TurnContract.state_lock(gateway):
        gateway.session.agent.messages = ModelContract.chat_history(
            gateway, request.key
        )
        context = getattr(gateway.session, "ctx", None)
        old_required = getattr(context, "subagent_approval_required", False)
        old_approved = getattr(context, "approved_work", False)
        if context is not None:
            context.subagent_approval_required = prepared.trusted_telegram
            context.approved_work = prepared.approved_work
        try:
            return gateway.session.ask(
                prepared.text,
                review_skills=TurnContract.command_trusted(gateway, request.channel),
                route_query=request.skill_query,
                record_turn=TurnContract.command_trusted(gateway, request.channel),
                session_id=request.session_id,
                trusted=TurnContract.command_trusted(gateway, request.channel),
            )
        finally:
            if context is not None:
                context.subagent_approval_required = old_required
                context.approved_work = old_approved
            ModelContract.save_chat_history(
                gateway, request.key, gateway.session.agent.messages
            )
