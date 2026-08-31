"""Locked gateway command dispatch and model-session acquisition."""

from __future__ import annotations

import threading
from typing import Protocol

from .. import pools, updater
from .turn_support import TURN_ERROR_REPLY, TurnContract, gateway_help_text
from .turn_types import (
    AskSession,
    CommandOutcome,
    CommandReply,
    ConversationKey,
    GatewayTurn,
    ModelLease,
    TurnLease,
    TurnRequest,
)


class GatewaySessionPool(Protocol):
    def borrow(self, key: ConversationKey) -> AskSession: ...

    def pop(self, key: ConversationKey) -> AskSession | None: ...


class SessionPoolContract:
    """Typed operations over the legacy dynamically typed session pool."""

    @staticmethod
    def borrow(pool: GatewaySessionPool, key: ConversationKey) -> AskSession:
        return pool.borrow(key)

    @staticmethod
    def pop(pool: GatewaySessionPool, key: ConversationKey) -> AskSession | None:
        return pool.pop(key)


class CommandContract(TurnContract, Protocol):
    """Public operations over the gateway command state."""

    @staticmethod
    def model_command(gateway: GatewayTurn, arg: str, key: ConversationKey) -> str:
        reply = gateway._models_command(arg)
        if gateway._hard_restart:
            gateway._restart_origin = key
        return reply

    @staticmethod
    def effort_command(gateway: GatewayTurn, arg: str, key: ConversationKey) -> str:
        reply = gateway._effort_command(arg)
        if gateway._hard_restart:
            gateway._restart_origin = key
        return reply

    @staticmethod
    def request_hard_restart(gateway: GatewayTurn, key: ConversationKey) -> None:
        gateway._hard_restart = True
        gateway._restart_origin = key

    @staticmethod
    def handle_omo(gateway: GatewayTurn, channel: str, chat_id: str, text: str) -> str:
        if not gateway._omo_command_trusted(channel, chat_id):
            return "OMO control is restricted to configured Telegram chat IDs."
        return gateway._omo_controller.handle(text)

    @staticmethod
    def borrowed_session(gateway: GatewayTurn, key: ConversationKey) -> AskSession:
        return SessionPoolContract.borrow(gateway._claude_sessions, key)

    @staticmethod
    def popped_session(gateway: GatewayTurn, key: ConversationKey) -> AskSession | None:
        return SessionPoolContract.pop(gateway._claude_sessions, key)

    @staticmethod
    def acquire_model_lease(
        gateway: GatewayTurn, key: ConversationKey
    ) -> CommandOutcome:
        persistent = gateway._persistent
        needs_seed = key not in gateway._history_seeded
        if needs_seed:
            gateway._history_seeded.add(key)
        session: AskSession | None = None
        if persistent:
            try:
                session = CommandContract.borrowed_session(gateway, key)
            except pools.SessionPoolFullError:
                return CommandReply(TURN_ERROR_REPLY)
        return ModelLease(
            TurnLease(
                persistent=persistent,
                needs_seed=needs_seed,
                token=object(),
                interrupted=threading.Event(),
                session=session,
            )
        )

    @staticmethod
    def new_conversation(gateway: GatewayTurn, key: ConversationKey) -> str:
        if gateway._persistent:
            old = CommandContract.popped_session(gateway, key)
            if old is not None:
                old.close()
        gateway._chats[key] = []
        _ = gateway._last_substantive_requests.pop(key, None)
        gateway._history_seeded.add(key)
        return "Started a new conversation."


def dispatch_command_or_acquire(
    gateway: GatewayTurn, request: TurnRequest
) -> CommandOutcome:
    command = request.command
    arg = request.command_arg
    channel = request.channel
    chat_id = request.chat_id
    key = request.key

    with CommandContract.state_lock(gateway):
        if command == "help":
            return CommandReply(gateway_help_text())
        if command == "models":
            return CommandReply(CommandContract.model_command(gateway, arg, key))
        if command == "effort":
            return CommandReply(CommandContract.effort_command(gateway, arg, key))
        if command == "hard_restart":
            CommandContract.request_hard_restart(gateway, key)
            print(
                f"[gateway] HARD restart requested via {channel}:{chat_id}",
                flush=True,
            )
            return CommandReply(
                "♻️ Hard restart — re-executing `birkin gateway` to pick up "
                + "code + config changes. Reconnecting in a moment…"
            )
        if command == "update":
            return CommandReply(_update_command(gateway, request))
        if command == "pending":
            return CommandReply(gateway.pending_text())
        if command == "omo":
            return CommandReply(
                CommandContract.handle_omo(gateway, channel, chat_id, request.text)
            )
        if command == "deny":
            return CommandReply(gateway.deny_command(arg))
        if command == "remind":
            return CommandReply(gateway.remind_command(arg, channel, chat_id))
        if command in ("commitment", "checkin", "companion"):
            return CommandReply(
                gateway.companion_command(command, arg, channel, chat_id)
            )
        if command == "restart":
            print(f"[gateway] restart requested via {channel}:{chat_id}", flush=True)
            return CommandReply(gateway.restart())
        if command == "new":
            return CommandReply(CommandContract.new_conversation(gateway, key))
        return _acquire_model_lease(gateway, key)


def _acquire_model_lease(gateway: GatewayTurn, key: ConversationKey) -> CommandOutcome:
    # Snapshot persistence and session together: /restart may otherwise change
    # the mode between this point and ask().
    return CommandContract.acquire_model_lease(gateway, key)


def _update_command(gateway: GatewayTurn, request: TurnRequest) -> str:
    result = updater.update()
    if result.get("updated"):
        CommandContract.request_hard_restart(gateway, request.key)
        print(
            "[gateway] update pulled new code via "
            + f"{request.channel}:{request.chat_id}; scheduling hard restart",
            flush=True,
        )
        return f"⬇️ {result['message']}\n" + "♻️ 새 코드를 반영하려고 재시작합니다…"
    return f"{'✅' if result.get('ok') else '⚠️'} {result['message']}"
