"""Typed contracts shared by gateway turn stages."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from ..claude_session import ClaudeStreamSession
from ..codex_session import CodexAppServerSession
from ..omo import OmoController
from ..pools import SessionPool
from ..runtime import Session

ProgressInfo = dict[str, object]
TextCallback = Callable[[str], None] | None
ProgressCallback = Callable[[ProgressInfo], None] | None
ConversationKey = tuple[str, str]


class AskSession(Protocol):
    @property
    def ask(self) -> Callable[..., str]: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class TurnRequest:
    channel: str
    chat_id: str
    text: str
    key: ConversationKey
    session_id: str
    command: str | None
    command_arg: str
    display_text: str
    skill_query: str
    sender_id: str | None = None


@dataclass(frozen=True, slots=True)
class TurnLease:
    persistent: bool
    needs_seed: bool
    token: object
    interrupted: threading.Event
    session: AskSession | None


@dataclass(frozen=True, slots=True)
class PreparedTurn:
    text: str
    trusted_telegram: bool
    approved_work: bool
    progress_seen: ProgressInfo
    watch_progress: Callable[[ProgressInfo], None]


@dataclass(frozen=True, slots=True)
class Admitted:
    request: TurnRequest


@dataclass(frozen=True, slots=True)
class Rejected:
    reply: str


AdmissionOutcome = Admitted | Rejected


@dataclass(frozen=True, slots=True)
class CommandReply:
    reply: str


@dataclass(frozen=True, slots=True)
class ModelLease:
    lease: TurnLease


CommandOutcome = CommandReply | ModelLease


class GatewayTurn(Protocol):
    @property
    def cfg(self) -> Mapping[str, object]: ...

    session: Session
    _lock: threading.Lock
    _persistent: bool
    _claude_sessions: SessionPool
    _chats: dict[ConversationKey, list[dict[str, object]]]
    _last_substantive_requests: dict[ConversationKey, str]
    _history_seeded: set[ConversationKey]
    _inflight: dict[ConversationKey, list[tuple[object, AskSession, threading.Event]]]
    _inflight_lock: threading.Lock
    _hard_restart: bool
    _restart_origin: ConversationKey | None
    _omo_controller: OmoController

    def _channel_trusted(
        self,
        channel: str,
        chat_id: str,
        sender_id: str | None = None,
    ) -> bool: ...

    def _command_trusted(self, channel: str) -> bool: ...

    def _autosave_trusted(self, channel: str) -> bool: ...

    def _omo_command_trusted(self, channel: str, chat_id: str) -> bool: ...

    def _models_command(self, arg: str) -> str: ...

    def _effort_command(self, arg: str) -> str: ...

    def pending_text(self) -> str: ...

    def deny_command(self, arg: str, *, actor_id: str, via: str) -> str: ...

    def remind_command(self, arg: str, channel: str, chat_id: str) -> str: ...

    def companion_command(
        self, cmd: str, arg: str, channel: str, chat_id: str
    ) -> str: ...

    def restart(self) -> str: ...

    def _build_claude_session(
        self, *, trusted: bool = True
    ) -> ClaudeStreamSession | CodexAppServerSession: ...

    def _record_failed_turn(
        self,
        display_text: str,
        reply: str,
        channel: str,
        chat_id: str,
    ) -> None: ...
